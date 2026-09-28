import shlex
from protocol import VERSION
from transport import ApiError
from ui import ACTIONS, LIMBS, PARTS, REASONS, Buttons, character_text, date, duration, skill_name, today


class Bot:
    def __init__(self, config, telegram, panel):
        self.config, self.tg, self.panel = config, telegram, panel
        self.buttons = Buttons()

    def button(self, actor, text, kind, **data):
        return self.buttons.add(actor, text, kind, **data)

    def menu(self, actor, chat, text='Liquidation 1.4.0 — управление сервером'):
        self.tg.send(chat, text, [
            [self.button(actor, '🟢 Онлайн', 'users', online=True), self.button(actor, '📊 Все игроки', 'users')],
            [self.button(actor, '📅 Время за сегодня', 'users', today_only=True)],
            [self.button(actor, '📋 Журнал операций', 'journal')]])

    def update(self, update):
        callback = update.get('callback_query')
        msg = callback.get('message', {}) if callback else update.get('message', {})
        sender = callback.get('from', {}) if callback else msg.get('from', {})
        actor = sender.get('id')
        chat = msg.get('chat', {})
        # Restrict control to private messages, bound to the authenticated user.
        if not isinstance(actor, int) or chat.get('type') != 'private' or chat.get('id') != actor:
            if callback:
                self.tg.call('answerCallbackQuery', callback_query_id=callback['id'], text='Используй личный чат с ботом.')
            return
        if callback:
            self.tg.call('answerCallbackQuery', callback_query_id=callback['id'])
        if not callback and msg.get('text', '').strip().split('@')[0] == '/myid':
            self.tg.send(actor, f'Твой Telegram ID: {actor}')
            return
        if actor not in self.config.admins:
            self.tg.send(actor, f'Доступ закрыт. Твой Telegram ID: {actor}. Владелец задаёт доступ через ADMIN_IDS.')
            return
        try:
            if callback:
                b = self.buttons.get(actor, callback.get('data'))
                if not b:
                    self.menu(actor, actor, 'Кнопка устарела или уже использована. Открой меню заново.')
                    return
                self.route(actor, b['kind'], b['data'])
            else:
                self.command(actor, msg.get('text', ''))
        except (ApiError, ValueError, KeyError) as error:
            # Only our own human-readable errors are delivered; no tracebacks or URLs.
            self.menu(actor, actor, str(error) if isinstance(error, (ApiError, ValueError)) else 'Запись больше не найдена. Открой меню заново.')

    def command(self, actor, text):
        try:
            args = shlex.split(text)
        except ValueError:
            raise ApiError('Закрой кавычки вокруг имени пользователя.') from None
        cmd = args[0].split('@')[0].lower() if args else ''
        if cmd in ('/start', '/menu', '/help'):
            self.menu(actor, actor, 'Liquidation 1.4.0\nВыбери игрока и персонажа кнопками.\n'
                '/player "Имя пользователя" — карточка\n/totaltime "Имя пользователя" — всё время\n'
                '/todaytime "Имя пользователя" — сегодня\n/myid — твой Telegram ID')
        elif cmd in ('/player', '/stats', '/totaltime', '/todaytime') and len(args) >= 2:
            state = self.panel.snapshot()
            user = ' '.join(args[1:])
            if cmd in ('/totaltime', '/todaytime'):
                self.report(actor, state, user, cmd == '/todaytime')
            else:
                self.user(actor, state, user)
        else:
            self.menu(actor, actor)

    def route(self, actor, kind, data):
        if kind == 'journal':
            journal = self.panel.journal()
            lines = ['Последние операции:']
            for r in journal:
                lines += [f'{date(int(r[1]))} | {ACTIONS.get(r[3], r[3])} | персонаж №{r[4]}',
                          f'Telegram ID {r[2]} | {r[6]}: {REASONS.get(r[7], r[7])}', f'Запрос: {r[0]}']
            self.menu(actor, actor, '\n'.join(lines) if journal else 'Операций пока нет.')
            return
        state = self.panel.snapshot()
        if kind == 'users':
            users = sorted({c.user for c in state.chars.values()
                if (not data.get('online') or c.online) and (not data.get('today_only') or today(state, c) > 0)}, key=str.casefold)
            page = data.get('page', 0)
            keys = [[self.button(actor, user, 'user', user=user)] for user in users[page*10:(page+1)*10]]
            if page > 0:
                keys.append([self.button(actor, '← Назад', 'users', **dict(data, page=page-1))])
            if (page+1)*10 < len(users):
                keys.append([self.button(actor, 'Далее →', 'users', **dict(data, page=page+1))])
            message = 'Выбери игрока:' if users else 'Подходящих записей пока нет.'
            if not state.enabled:
                message += '\nУправление отключено: проверь remote_admins.txt и журнал в консоли сервера.'
            if not state.fresh():
                message += '\nСнимок от ' + date(state.stamp, state.offset) + '; данные об онлайне могут устареть.'
            self.tg.send(actor, message, keys)
        elif kind == 'user':
            self.user(actor, state, data['user'], data.get('page', 0))
        elif kind == 'report':
            self.report(actor, state, data['user'], data.get('today', False))
        elif kind == 'confirm':
            self.confirm(actor, state, data)
        else:
            c = state.chars[data['cid']]
            if kind == 'character':
                self.character(actor, state, c)
            elif kind == 'skills':
                self.skills(actor, state, c, data.get('page', 0))
            elif kind == 'level':
                self.controllable(state, c)
                s = c.skills[data['perk']]
                buttons = [self.button(actor, str(level), 'preview', cid=c.id, action='setskill', arg=s.id+':'+str(level)) for level in range(11)]
                self.tg.send(actor, f'{skill_name(s)}: сейчас {s.level}/10. Выбери новый уровень.\n'
                    'XP будет установлен на начало выбранного уровня.', [buttons[i:i+4] for i in range(0, 11, 4)])
            elif kind == 'parts':
                self.controllable(state, c)
                action = data['action']
                parts = LIMBS if action == 'amputate' else PARTS.keys()
                buttons = [self.button(actor, PARTS[p], 'preview', cid=c.id, action=action, arg=p)
                    for p in parts if not (c.toc == 'ready' and p in c.amputated)]
                self.tg.send(actor, f'{ACTIONS[action]} — выбери часть тела «{c.name}»: ',
                             [buttons[i:i+2] for i in range(0, len(buttons), 2)])
            elif kind == 'sources':
                self.controllable(state, c)
                sources = [s for s in state.chars.values() if s.user == c.user and not s.alive and s.skills_at > 0 and s.skills]
                page = data.get('page', 0)
                keys = [[self.button(actor, f'№{s.id} {s.name}', 'preview', cid=c.id, action='transfer', arg=str(s.id))]
                        for s in sources[page*10:(page+1)*10]]
                if page > 0:
                    keys.append([self.button(actor, '← Назад', 'sources', cid=c.id, page=page-1)])
                if (page+1)*10 < len(sources):
                    keys.append([self.button(actor, 'Далее →', 'sources', cid=c.id, page=page+1)])
                self.tg.send(actor, 'Выбери умершего персонажа — источник навыков:' if sources else
                    'Нет умерших персонажей этого игрока с сохранёнными навыками. Запись навыков начинается с версии 1.4.0.', keys)
            elif kind == 'preview':
                self.preview(actor, state, c, data['action'], data.get('arg', '-'))

    def user(self, actor, state, user, page=0):
        chars = [c for c in state.chars.values() if c.user == user]
        if not chars:
            raise ApiError('Игрока с таким именем нет в истории мода. Регистр учитывается.')
        keys = [[self.button(actor, ('🟢 ' if c.online and state.fresh() else '') + f'№{c.id} {c.name}', 'character', cid=c.id)] for c in chars[page*10:(page+1)*10]]
        if page:
            keys.append([self.button(actor, '← Назад', 'user', user=user, page=page-1)])
        if (page+1)*10 < len(chars):
            keys.append([self.button(actor, 'Далее →', 'user', user=user, page=page+1)])
        keys += [[self.button(actor, 'Всё время', 'report', user=user), self.button(actor, 'Сегодня', 'report', user=user, today=True)]]
        self.tg.send(actor, f'Игрок {user}\nВсего: {duration(sum(c.total for c in chars))}\n'
            f'Сегодня: {duration(sum(today(state, c) for c in chars))}\nПерсонажей: {len(chars)}', keys)

    def report(self, actor, state, user, only_today):
        chars = [c for c in state.chars.values() if c.user == user and (not only_today or today(state, c) > 0)]
        lines = [f'Игрок {user} — ' + ('за сегодня' if only_today else 'всё время'),
                 'Итого: ' + duration(sum(today(state, c) if only_today else c.total for c in chars))]
        for c in chars:
            if only_today:
                lines += [f'\n«{c.name}» [№{c.id}] — {"жив" if c.alive else "мёртв"}', duration(today(state, c))]
            else:
                lines += ['\n' + character_text(state, c)]
        if not state.fresh():
            lines += ['Сервер не прислал свежих данных; показано последнее сохранённое время.']
        self.menu(actor, actor, '\n'.join(lines))

    def character(self, actor, state, c):
        keys = [[self.button(actor, '📚 Навыки', 'skills', cid=c.id)]]
        if c.online and state.fresh() and state.enabled:
            keys += [[self.button(actor, '💚 Отхил', 'preview', cid=c.id, action='heal'),
                      self.button(actor, '💀 Убить', 'preview', cid=c.id, action='kill')]]
            keys += [[self.button(actor, ACTIONS[a], 'parts', cid=c.id, action=a)] for a in ('bite', 'cut', 'scratch')]
            if c.toc == 'ready':
                keys += [[self.button(actor, 'Ампутация', 'parts', cid=c.id, action='amputate')]]
            keys += [[self.button(actor, 'Перенести навыки умершего', 'sources', cid=c.id)]]
        keys += [[self.button(actor, '↻ Обновить', 'character', cid=c.id), self.button(actor, 'К игроку', 'user', user=c.user)]]
        self.tg.send(actor, character_text(state, c), keys)

    def skills(self, actor, state, c, page):
        skills = sorted(c.skills.values(), key=lambda s: skill_name(s).casefold())
        text = [f'Навыки «{c.name}» [№{c.id}]', 'Записаны: ' + date(c.skills_at, state.offset)]
        text += [f'{skill_name(s)}: {s.level}/10 · XP {s.xp:g}' for s in skills[page*10:(page+1)*10]]
        if not skills:
            text = ['Навыки этого персонажа ещё не записаны.']
        keys = []
        if c.online and state.enabled and state.fresh():
            keys += [[self.button(actor, skill_name(s) + f' ({s.level})', 'level', cid=c.id, perk=s.id)] for s in skills[page*10:(page+1)*10]]
        if page > 0:
            keys += [[self.button(actor, '← Назад', 'skills', cid=c.id, page=page-1)]]
        if (page+1)*10 < len(skills):
            keys += [[self.button(actor, 'Далее →', 'skills', cid=c.id, page=page+1)]]
        keys += [[self.button(actor, 'К персонажу', 'character', cid=c.id)]]
        self.tg.send(actor, '\n'.join(text), keys)

    @staticmethod
    def controllable(state, c):
        if state.version != VERSION:
            raise ApiError('Версии бота и мода отличаются. Обнови обе части до 1.4.0.')
        if not state.fresh():
            raise ApiError('Сервер не прислал свежий снимок. Управление временно недоступно.')
        if not state.enabled:
            raise ApiError('Управление отключено: добавь Telegram ID в remote_admins.txt и проверь журнал сервера.')
        if not c.online:
            raise ApiError('Этот персонаж сейчас не в игре.')

    def preview(self, actor, state, c, action, arg):
        self.controllable(state, c)
        text = f'Подтвердить: {ACTIONS[action]}\nИгрок: {c.user}\nПерсонаж: «{c.name}» [№{c.id}]'
        if action in ('bite', 'cut', 'scratch', 'amputate'):
            text += '\nЧасть тела: ' + PARTS[arg]
            if action == 'amputate':
                text += '\nАмпутация как в админ-меню The Only Cure: без хирургического урона. Отсутствующие части ниже места ампутации учитываются автоматически.'
            else:
                text += '\nЗаражение определяется механикой раны и настройками сервера.'
        elif action == 'heal':
            text += '\nЛечение ран, инфекции и состояний WoundsOverhaul. Ампутации сохраняются.'
        elif action == 'setskill':
            sid, level = arg.rsplit(':', 1)
            text += f'\n{skill_name(c.skills[sid])}: {c.skills[sid].level} → {level}. XP — начало выбранного уровня.'
        elif action == 'transfer':
            source = state.chars[int(arg)]
            if source.user != c.user or source.alive or not source.skills:
                raise ApiError('Источник навыков недоступен.')
            text += f'\nИсточник: «{source.name}» [№{source.id}], мёртв.\nСнимок навыков: {date(source.skills_at, state.offset)}'
            text += f'\nУровни и XP {len(source.skills)} навыков будут заменены сохранёнными значениями, включая силу и физподготовку.'
        self.tg.send(actor, text, [[self.button(actor, '✅ Подтвердить', 'confirm', cid=c.id,
            boot=state.boot, session=c.session, action=action, arg=arg)],
            [self.button(actor, 'Отмена', 'character', cid=c.id)]])

    def confirm(self, actor, state, data):
        c = state.chars[data['cid']]
        self.controllable(state, c)
        if state.boot != data['boot'] or c.session != data['session']:
            raise ApiError('Персонаж или сервер сменил сессию. Требуется новое подтверждение.')
        self.tg.send(actor, 'Запрос отправляется на сервер…')
        argument = data['arg']
        if data['action'] == 'setskill':
            sid, level = argument.rsplit(':', 1)
            argument = sid.encode('utf-8').hex() + ':' + level
        status, code, rid = self.panel.execute(actor, state, c, data['action'], argument)
        title = {'ok': '✅ Выполнено', 'rejected': 'Действие отклонено', 'partial': '⚠️ Результат требует проверки',
                 'unknown': '⚠️ Итог неизвестен'}.get(status, 'Итог неизвестен')
        self.menu(actor, actor, title + '\n' + REASONS.get(code, code) + '\nЗапрос: ' + rid)
