import shlex
import time
from protocol import VERSION
from transport import ApiError, TelegramError
from ui import ACTIONS, LIMBS, PARTS, limb_parts, REASONS, Buttons, character_text, date, duration, skill_name, today, restore_parts, text_pages


class UIError(ApiError):
    pass


class Bot:
    def __init__(self, config, telegram, panel):
        self.config, self.tg, self.panel = config, telegram, panel
        self.buttons = Buttons()
        self.messages, self.context, self.results = {}, {}, {}
        self.host_context, self.host_results = set(), {}

    def button(self, actor, text, kind, **data):
        return self.buttons.add(actor, text, kind, **data)

    def show(self, actor, text, buttons=None):
        self.page(actor, text_pages(text), buttons or [], 0)

    def page(self, actor, pages, keys, page):
        page = max(0, min(page, len(pages)-1))
        buttons = list(keys)
        if len(pages) > 1:
            nav = []
            for title, index in [('← Страница', page-1), ('Страница →', page+1)]:
                if 0 <= index < len(pages):
                    nav.append(self.button(actor, title, 'textpage', pages=pages, keys=keys, page=index))
            buttons = [nav] + buttons
        text = pages[page] + (f'\n\nСтраница {page+1}/{len(pages)}' if len(pages) > 1 else '')
        mid = self.messages.get(actor)
        try:
            if mid is not None:
                try:
                    self.tg.edit(actor, mid, text, buttons)
                except TelegramError as error:
                    if error.reason != 'not_editable':
                        raise
                    # Only a definitive "deleted/uneditable" permits a new message.
                    result = self.tg.send(actor, text, buttons)
                    self.messages[actor] = result['message_id']
            else:
                result = self.tg.send(actor, text, buttons)
                self.messages[actor] = result['message_id']
        except ApiError as error:
            # A network timeout may mean the edit succeeded. Never flood or retry
            # the game action because displaying its result failed.
            raise UIError(str(error)) from None
        self.buttons.retain(actor, {b['callback_data'] for row in buttons for b in row})

    def character_back(self, actor, c):
        return [self.button(actor, 'К персонажу', 'character', cid=c.id)]

    def problem(self, actor, message):
        if actor in self.host_context:
            self.host_menu(actor, message)
            return
        context = self.context.get(actor)
        if context:
            state, c = context
            self.character(actor, state, c, message)
        else:
            self.menu(actor, actor, message)

    def menu(self, actor, chat, text='Liquidation 1.5.0.6.9 — управление сервером'):
        self.context.pop(actor, None)
        self.host_context.discard(actor)
        self.show(chat, text, [
            [self.button(actor, '🟢 Онлайн', 'users', online=True), self.button(actor, '📊 Все игроки', 'users')],
            [self.button(actor, '📅 Время за сегодня', 'users', today_only=True)],
            [self.button(actor, '📋 Журнал операций', 'journal')],
            [self.button(actor, 'Управление сервером', 'host')]])

    def host_menu(self, actor, notice=None):
        self.context.pop(actor, None)
        self.host_context.add(actor)
        notice = notice if notice is not None else self.host_results.get(actor, '')
        try:
            status = self.panel.api('resources')
            label = {'running': 'запущен', 'offline': 'выключен', 'starting': 'запускается',
                     'stopping': 'выключается'}[status['state']]
            if status['suspended']:
                label += '; приостановлен хостингом'
        except ApiError as error:
            label = 'не удалось получить — ' + str(error)
        titles = [('save', 'Сохранение мира'), ('check', 'Проверка апдейтов'),
                  ('restart', 'Перезапуск сервера'), ('stop', 'Выключение сервера'),
                  ('start', 'Включение сервера')]
        keys = [[self.button(actor, title, 'hostpreview', action=action, label=title)] for action, title in titles]
        keys += [[self.button(actor, '↻ Обновить состояние', 'host')], [self.button(actor, 'Главное меню', 'menu')]]
        self.show(actor, (notice + '\n\n' if notice else '') + 'Управление сервером\nСостояние панели: ' + label +
                  '\nУправление доступно и при выключенной игре. Проверка апдейтов проверяет моды Workshop.', keys)

    def host_preview(self, actor, data):
        self.context.pop(actor, None)
        self.host_context.add(actor)
        self.panel.host_allowed(actor)
        status = self.panel.api('resources')
        self.panel.host_ready(data['action'], status)
        notes = {
            'save': 'Передать команду сохранения текущего мира в консоль?',
            'check': 'Запросить проверку обновлений модов Steam Workshop? Результат будет в консоли и игровом чате.',
            'restart': 'Перезапустить сервер сейчас через панель? Игроки будут отключены. Пятиминутного отсчёта watchdog здесь нет.',
            'stop': 'Выключить сервер сейчас через обычную остановку панели? Игроки будут отключены.',
            'start': 'Включить сервер через панель EGNetwork?'}
        self.show(actor, data['label'] + '\n' + notes[data['action']], [
            [self.button(actor, '✅ Подтвердить', 'hostconfirm', action=data['action'], label=data['label'],
                         preview=status, offered=time.monotonic())],
            [self.button(actor, 'Отмена', 'host')]])

    def host_confirm(self, actor, data):
        if not 0 <= time.monotonic() - data['offered'] <= 60:
            raise ApiError('Подтверждение устарело. Выбери действие сервера заново.')
        self.show(actor, 'Отправляю запрос: ' + data['label'] + '…')
        result = self.panel.host_action(actor, data['action'], data['preview'])
        self.host_results[actor] = data['label'] + '\n' + result
        self.host_menu(actor)

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
            self.show(actor, f'Твой Telegram ID: {actor}')
            return
        if actor not in self.config.admins:
            self.show(actor, f'Доступ закрыт. Твой Telegram ID: {actor}. Владелец задаёт доступ через ADMIN_IDS.')
            return
        try:
            if callback:
                mid = msg.get('message_id')
                if isinstance(mid, int):
                    self.messages[actor] = mid
                b = self.buttons.get(actor, callback.get('data'))
                if not b:
                    self.problem(actor, 'Кнопка устарела или уже использована. Выбери действие заново.')
                    return
                self.route(actor, b['kind'], b['data'])
            else:
                self.command(actor, msg.get('text', ''))
        except UIError:
            raise
        except (ApiError, ValueError, KeyError) as error:
            # Only our own human-readable errors are delivered; no tracebacks or URLs.
            self.problem(actor, str(error) if isinstance(error, (ApiError, ValueError)) else 'Запись больше не найдена. Открой меню заново.')

    def command(self, actor, text):
        try:
            args = shlex.split(text)
        except ValueError:
            raise ApiError('Закрой кавычки вокруг имени пользователя.') from None
        cmd = args[0].split('@')[0].lower() if args else ''
        if cmd in ('/start', '/menu', '/help'):
            self.menu(actor, actor, 'Liquidation 1.5.0.6.9\nВыбери игрока и персонажа кнопками.\n'
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
        if kind == 'textpage':
            self.page(actor, data['pages'], data['keys'], data['page'])
            return
        if kind == 'menu':
            self.menu(actor, actor)
            return
        if kind == 'host':
            self.host_menu(actor)
            return
        if kind == 'hostpreview':
            self.host_preview(actor, data)
            return
        if kind == 'hostconfirm':
            self.host_confirm(actor, data)
            return
        self.host_context.discard(actor)
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
            self.context.pop(actor, None)
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
            keys.append([self.button(actor, 'Главное меню', 'menu')])
            self.show(actor, message, keys)
        elif kind == 'user':
            self.user(actor, state, data['user'], data.get('page', 0))
        elif kind == 'report':
            self.report(actor, state, data['user'], data.get('today', False))
        elif kind == 'confirm':
            self.confirm(actor, state, data)
        else:
            c = state.chars[data['cid']]
            self.context[actor] = (state, c)
            if kind == 'character':
                self.character(actor, state, c)
            elif kind == 'skills':
                self.skills(actor, state, c, data.get('page', 0))
            elif kind == 'level':
                self.controllable(state, c)
                s = c.skills[data['perk']]
                buttons = [self.button(actor, str(level), 'preview', cid=c.id, action='setskill', arg=s.id+':'+str(level)) for level in range(11)]
                self.show(actor, f'{skill_name(s)}: сейчас {s.level}/10. Выбери новый уровень.\n'
                    'XP будет установлен на начало выбранного уровня.', [buttons[i:i+4] for i in range(0, 11, 4)] + [self.character_back(actor, c)])
            elif kind == 'parts':
                self.controllable(state, c)
                action = data['action']
                parts = restore_parts(c) if action == 'restore' else limb_parts(c) if action == 'amputate' else PARTS.keys()
                buttons = [self.button(actor, PARTS[p], 'preview', cid=c.id, action=action, arg=p)
                    for p in parts if action == 'restore' or not (c.limbs_ready and p in c.amputated)]
                self.show(actor, f'{ACTIONS[action]} — выбери часть тела «{c.name}»:' if buttons else 'Нет подходящих частей тела.',
                             [buttons[i:i+2] for i in range(0, len(buttons), 2)] + [self.character_back(actor, c)])
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
                self.show(actor, 'Выбери умершего персонажа — источник навыков:' if sources else
                    'Нет умерших персонажей этого игрока с сохранёнными навыками. Запись навыков начинается с версии 1.4.0.', keys + [self.character_back(actor, c)])
            elif kind == 'preview':
                self.preview(actor, state, c, data['action'], data.get('arg', '-'))

    def user(self, actor, state, user, page=0):
        self.context.pop(actor, None)
        chars = [c for c in state.chars.values() if c.user == user]
        if not chars:
            raise ApiError('Игрока с таким именем нет в истории мода. Регистр учитывается.')
        keys = [[self.button(actor, ('🟢 ' if c.online and state.fresh() else '') + f'№{c.id} {c.name}', 'character', cid=c.id)] for c in chars[page*10:(page+1)*10]]
        if page:
            keys.append([self.button(actor, '← Назад', 'user', user=user, page=page-1)])
        if (page+1)*10 < len(chars):
            keys.append([self.button(actor, 'Далее →', 'user', user=user, page=page+1)])
        keys += [[self.button(actor, 'Всё время', 'report', user=user), self.button(actor, 'Сегодня', 'report', user=user, today=True)]]
        keys.append([self.button(actor, 'Главное меню', 'menu')])
        self.show(actor, f'Игрок {user}\nВсего: {duration(sum(c.total for c in chars))}\n'
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
        self.show(actor, '\n'.join(lines), [[self.button(actor, 'К игроку', 'user', user=user)]])

    def character(self, actor, state, c, notice=None):
        self.context[actor] = (state, c)
        if notice is None and self.results.get(actor, (None,))[0] == c.id:
            notice = self.results[actor][1]
        keys = [[self.button(actor, '📚 Навыки', 'skills', cid=c.id)]]
        if c.online and state.fresh() and state.enabled:
            keys += [[self.button(actor, '💚 Отхил', 'preview', cid=c.id, action='heal'),
                      self.button(actor, '💀 Убить', 'preview', cid=c.id, action='kill')]]
            keys += [[self.button(actor, ACTIONS[a], 'parts', cid=c.id, action=a)] for a in ('bite', 'cut', 'scratch', 'deep')]
            if c.limbs_ready:
                keys += [[self.button(actor, 'Ампутация', 'parts', cid=c.id, action='amputate')]]
                if c.amputated:
                    keys += [[self.button(actor, '🦾 Вернуть конечность', 'parts', cid=c.id, action='restore')]]
            keys += [[self.button(actor, 'Перенести навыки умершего', 'sources', cid=c.id)]]
        keys += [[self.button(actor, '↻ Обновить', 'character', cid=c.id), self.button(actor, 'К игроку', 'user', user=c.user)]]
        keys += [[self.button(actor, 'Главное меню', 'menu')]]
        self.show(actor, (notice + '\n\n' if notice else '') + character_text(state, c), keys)

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
        self.show(actor, '\n'.join(text), keys)

    @staticmethod
    def controllable(state, c):
        if state.version != VERSION:
            raise ApiError('Версии бота и мода отличаются. Обнови обе части до 1.5.0.6.9.')
        if not state.fresh():
            raise ApiError('Сервер не прислал свежий снимок. Управление временно недоступно.')
        if not state.enabled:
            raise ApiError('Управление отключено: добавь Telegram ID в remote_admins.txt и проверь журнал сервера.')
        if not c.online:
            raise ApiError('Этот персонаж сейчас не в игре.')

    def preview(self, actor, state, c, action, arg):
        self.context[actor] = (state, c)
        self.controllable(state, c)
        text = f'Подтвердить: {ACTIONS[action]}\nИгрок: {c.user}\nПерсонаж: «{c.name}» [№{c.id}]'
        if action in ('bite', 'cut', 'scratch', 'deep', 'amputate', 'restore'):
            text += '\nЧасть тела: ' + PARTS[arg]
            if action == 'restore':
                if not c.limbs_ready or arg not in restore_parts(c):
                    raise ApiError('Место ампутации изменилось. Выбери конечность заново.')
                if c.limb_provider == 'cu':
                    text += '\nCasualties Undead восстановит всю выбранную руку или ногу. Установленный протез вернётся в инвентарь.'
                else:
                    text += '\nВернётся выбранная часть и части руки ниже неё. Протез на этой руке будет снят и останется в инвентаре.'
                    text += '\nЧерта врождённой ампутации этой руки, если есть, будет удалена.'
            elif action == 'amputate':
                if not c.limbs_ready or arg not in limb_parts(c) or arg in c.amputated:
                    raise ApiError('Эта ампутация сейчас недоступна. Обнови карточку персонажа.')
                if c.limb_provider == 'cu':
                    text += '\nОперация Casualties Undead: появятся глубокая рана культи, боль и кровотечение. Возможны заражение и смерть без лечения. Протез вернётся в инвентарь.'
                else:
                    text += '\nАмпутация как в админ-меню The Only Cure: без хирургического урона.'
            else:
                text += '\nЗаражение определяется механикой раны и настройками сервера.'
        elif action == 'heal':
            text += '\nЛечение ран и инфекции. Ампутации сохраняются.'
            if c.limb_provider == 'cu':
                text += '\nCasualties Undead: кровь, органы, ритм сердца, состояния болезней и культей. Утраченные глаза и история психических травм сохраняются.'
            if c.wounds:
                text += '\nОчистка медицинских состояний Wounds Overhaul.'
        elif action == 'setskill':
            sid, level = arg.rsplit(':', 1)
            text += f'\n{skill_name(c.skills[sid])}: {c.skills[sid].level} → {level}. XP — начало выбранного уровня.'
        elif action == 'transfer':
            source = state.chars[int(arg)]
            if source.user != c.user or source.alive or not source.skills:
                raise ApiError('Источник навыков недоступен.')
            text += f'\nИсточник: «{source.name}» [№{source.id}], мёртв.\nСнимок навыков: {date(source.skills_at, state.offset)}'
            text += f'\nУровни и XP {len(source.skills)} навыков будут заменены сохранёнными значениями, включая силу и физподготовку.'
        self.show(actor, text, [[self.button(actor, '✅ Подтвердить', 'confirm', cid=c.id,
            boot=state.boot, session=c.session, action=action, arg=arg)],
            [self.button(actor, 'Отмена', 'character', cid=c.id)]])

    def confirm(self, actor, state, data):
        c = state.chars[data['cid']]
        self.controllable(state, c)
        if state.boot != data['boot'] or c.session != data['session']:
            raise ApiError('Персонаж или сервер сменил сессию. Требуется новое подтверждение.')
        self.context[actor] = (state, c)
        self.show(actor, f'Запрос отправляется на сервер…\nПерсонаж: «{c.name}» [№{c.id}]')
        argument = data['arg']
        if data['action'] == 'setskill':
            sid, level = argument.rsplit(':', 1)
            argument = sid.encode('utf-8').hex() + ':' + level
        status, code, rid = self.panel.execute(actor, state, c, data['action'], argument)
        title = {'ok': '✅ Выполнено', 'rejected': 'Действие отклонено', 'partial': '⚠️ Результат требует проверки',
                 'unknown': '⚠️ Итог неизвестен'}.get(status, 'Итог неизвестен')
        notice = title + '\n' + REASONS.get(code, code) + '\nЗапрос: ' + rid
        self.results[actor] = (c.id, notice)
        try:
            latest = self.panel.snapshot()
            current = latest.chars[c.id]
        except (ApiError, ValueError, KeyError):
            # The action already ran. Retain its receipt, never submit it again.
            import copy
            latest, current = copy.copy(state), c
            latest.enabled = False
            notice += '\nКарточка пока не обновилась. Нажми «Обновить»; действие повторять не нужно.'
        self.character(actor, latest, current, notice)
