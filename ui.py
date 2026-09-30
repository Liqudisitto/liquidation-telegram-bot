from datetime import datetime, timezone, timedelta
import secrets
import time

PARTS = {
    'Hand_L': 'Левая кисть', 'Hand_R': 'Правая кисть',
    'ForeArm_L': 'Левое предплечье', 'ForeArm_R': 'Правое предплечье',
    'UpperArm_L': 'Левое плечо', 'UpperArm_R': 'Правое плечо',
    'Torso_Upper': 'Верх туловища', 'Torso_Lower': 'Низ туловища',
    'Head': 'Голова', 'Neck': 'Шея', 'Groin': 'Пах',
    'UpperLeg_L': 'Левое бедро', 'UpperLeg_R': 'Правое бедро',
    'LowerLeg_L': 'Левая голень', 'LowerLeg_R': 'Правая голень',
    'Foot_L': 'Левая стопа', 'Foot_R': 'Правая стопа',
}
LIMBS = ('Hand_L', 'ForeArm_L', 'UpperArm_L', 'Hand_R', 'ForeArm_R', 'UpperArm_R')
CU_LIMBS = LIMBS + ('Foot_L', 'LowerLeg_L', 'UpperLeg_L', 'Foot_R', 'LowerLeg_R', 'UpperLeg_R')


def limb_parts(character):
    return CU_LIMBS if character.limb_provider == 'cu' else LIMBS


SKILLS = {'Fitness': 'Физподготовка', 'Strength': 'Сила', 'Sprinting': 'Бег',
    'Lightfoot': 'Лёгкий шаг', 'Nimble': 'Проворность', 'Sneak': 'Скрытность',
    'Axe': 'Топоры', 'Blunt': 'Длинное дробящее', 'SmallBlunt': 'Короткое дробящее',
    'LongBlade': 'Длинное режущее', 'SmallBlade': 'Короткое режущее', 'Spear': 'Копья',
    'Maintenance': 'Обслуживание', 'Woodwork': 'Строительство', 'Cooking': 'Кулинария',
    'Farming': 'Земледелие', 'Doctor': 'Первая помощь', 'Electricity': 'Электрика',
    'MetalWelding': 'Сварка', 'Mechanics': 'Механика', 'Tailoring': 'Шитьё',
    'Aiming': 'Стрельба', 'Reloading': 'Перезарядка', 'Fishing': 'Рыбалка',
    'Trapping': 'Ловушки', 'PlantScavenging': 'Собирательство', 'FlintKnapping': 'Обработка камня',
    'Carving': 'Резьба', 'Butchering': 'Разделка', 'Husbandry': 'Животноводство',
    'Tracking': 'Выслеживание', 'Pottery': 'Гончарное дело', 'Glassmaking': 'Стеклоделие',
    'Masonry': 'Каменная кладка', 'Blacksmith': 'Кузнечное дело', 'Welding': 'Сварка'}
ACTIONS = {'heal': 'Полный отхил', 'kill': 'Убить персонажа', 'bite': 'Укус',
    'scratch': 'Царапина', 'cut': 'Рваная рана', 'deep': 'Глубокая рана', 'amputate': 'Ампутация',
    'restore': 'Восстановить конечность',
    'setskill': 'Изменение навыка', 'transfer': 'Перенос навыков'}
REASONS = {
    'cu_amputated': 'Ампутация подтверждена Casualties Undead и клиентом игрока. Культя требует лечения.',
    'cu_not_ready': 'Casualties Undead ещё не готов или его API изменился. Проверь версию мода и консоль.',
    'cu_not_confirmed': 'Нет полного подтверждения ампутации. Проверь персонажа перед повтором.',
    'medical_mod_conflict': 'Casualties Undead и The Only Cure несовместимы: оставь включённым один из них.',
    'limb_adapter_absent': 'Нет готового поддерживаемого мода ампутаций.',
    'unsupported_limb': 'Этот мод не поддерживает выбранную конечность.',
    'healed': 'Здоровье восстановлено, клиент подтвердил очистку состояний. Ампутации сохранены.',
    'killed': 'Смерть персонажа подтверждена сервером.',
    'amputated': 'Ампутация подтверждена The Only Cure.',
    'limb_restored': 'Конечность восстановлена. Сервер и клиент подтвердили результат.',
    'limb_present': 'Эта конечность уже на месте.',
    'restore_parent_first': 'Выбери верхнюю точку ампутации: она восстановится вместе с нижними частями руки.',
    'restore_error': 'Восстановление завершилось не полностью. Проверь персонажа перед повтором.',
    'restore_not_confirmed': 'Нет полного подтверждения восстановления от клиента. Проверь персонажа и журнал.',
    'restore_adapter_unavailable': 'Адаптер восстановления несовместим с этой версией The Only Cure.',
    'wound_applied': 'Рана добавлена и отправлена клиенту.',
    'skills_updated': 'Уровни и XP обновлены на сервере.',
    'target_changed': 'Персонаж вышел, умер или сменился. Открой его карточку заново.',
    'expired': 'Запрос устарел или сервер перезапустился.',
    'admin_not_allowed': 'Твой Telegram ID не указан в remote_admins.txt на игровом сервере.',
    'busy': 'Сервер ещё завершает другую операцию.',
    'journal_unavailable': 'Сервер не может надёжно записать журнал. Команды заблокированы.',
    'save_unavailable': 'Не удалось сохранить статистику перед действием.',
    'target_godmode': 'У персонажа включено бессмертие. Сначала отключи его в игре.',
    'toc_not_ready': 'The Only Cure не установлен или ещё не загрузил данные персонажа.',
    'limb_missing': 'Эта часть тела уже ампутирована.',
    'source_not_dead_same_user': 'Источник должен быть умершим персонажем того же игрока.',
    'source_skills_unknown': 'У этого умершего персонажа нет сохранённой записи навыков.',
    'source_skill_unavailable': 'Один из сохранённых навыков отсутствует в текущем наборе модов.',
    'skill_definition_changed': 'Таблица XP навыка изменилась. Автоматический перенос отменён.',
    'unknown_skill': 'Навык не найден или уровень вне диапазона 0–10.',
    'xp_api_unavailable': 'В этой версии игры недоступен необходимый метод изменения XP.',
    'wounds_adapter_unavailable': 'Не загрузились функции WoundsOverhaul для полного отхила.',
    'client_adapter_unavailable': 'На клиенте отсутствует нужная версия Liquidation или медицинского адаптера.',
    'admin_revoked': 'Во время операции доступ администратора был отозван.',
    'response_timeout': 'Подтверждение не получено. Проверь персонажа и журнал перед повтором.',
    'delivery_unknown': 'Неизвестно, дошёл ли запрос. Проверь персонажа и журнал перед повтором.',
    'client_timeout_check_player': 'Итог не подтверждён вовремя. Действие могло уже примениться на сервере. Проверь персонажа перед повтором.',
    'client_prepare_timeout': 'Клиент не подтвердил готовность за 10 секунд. Действие не применялось. Проверь /liquidusversion и журнал игры на ПК.',
    'client_version_mismatch': 'На ПК игрока загружена старая или смешанная сборка Liquidus. Нужна 1.5.0.6.9 FIX1 целиком. Проверь /liquidusversion, убери старую локальную копию Workshop и полностью перезапусти игру.',
    'client_bridge_missing': 'Клиентский модуль управления ещё не подтвердил загрузку. Подожди 5 секунд и обнови карточку. Если ошибка остаётся: нужна 1.5.0.6.9 FIX1 на ПК, проверь /liquidusversion и журнал игры.',
    'client_bridge_stale': 'Клиентский модуль управления перестал отвечать. Обнови карточку через 5 секунд; если связь не восстановится, перезайди и проверь журнал игры.',
    'client_adapter_error': 'Ошибка медицинского адаптера на ПК игрока. Действие не применялось. Нужен console.txt с ПК за момент запроса.',
    'started_no_final_result': 'Запрос был принят, итог не сохранён. Автоповтора не будет.',
    'execution_error_check_player': 'Ошибка при выполнении. Изменения могли примениться частично.',
    'heal_error': 'Отхил завершился с ошибкой; требуется проверка персонажа.',
    'heal_client_not_confirmed': 'Сервер изменил здоровье, но полный отхил не подтверждён.',
    'skills_not_confirmed': 'Результат изменения навыков не совпал с ожидаемым. Проверь в игре.',
    'adapter_error': 'Ошибка совместимости. Проверь консоль игрового сервера.',
}


def word(n, forms):
    if 11 <= n % 100 <= 14:
        return forms[2]
    return forms[0] if n % 10 == 1 else forms[1] if n % 10 in (2, 3, 4) else forms[2]


def duration(ms):
    seconds = max(0, int(ms) // 1000)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f'{h} {word(h, ("час", "часа", "часов"))}, {m} {word(m, ("минута", "минуты", "минут"))}, {s} {word(s, ("секунда", "секунды", "секунд"))}'


def date(value, offset=180, real=True):
    if value < 0:
        return 'неизвестно — персонаж существовал до начала учёта'
    try:
        return datetime.fromtimestamp(value / 1000 if real else value,
            timezone(timedelta(minutes=offset if real else 0))).strftime('%d.%m.%Y %H:%M:%S')
    except (ValueError, OverflowError, OSError):
        return 'неизвестно'


def today(state, c):
    day = datetime.now(timezone(timedelta(minutes=state.offset))).strftime('%Y-%m-%d')
    return c.today if day == state.day else 0


def skill_name(s):
    return SKILLS.get(s.id, s.name or s.id)


CAUSES = {'unknown': 'не установлена', 'admin_kill': 'убийство через Telegram-бота',
    'knox': 'Нокс-вирус', 'bleeding': 'кровотечение от ран',
    'blood_loss': 'тяжёлая кровопотеря', 'sepsis': 'сепсис', 'fire': 'огонь / ожоги'}
WOUNDS = {'bite': 'укус', 'scratch': 'царапина', 'cut': 'рваная рана', 'deep': 'глубокая рана',
    'bleeding': 'кровотечение', 'burn': 'ожог', 'fracture': 'перелом', 'bullet': 'пуля в теле',
    'glass': 'осколок стекла', 'infected': 'инфекция раны', 'bandaged': 'повязка', 'stitched': 'швы'}
TOWNS = {'Muldraugh': 'Малдро', 'Rosewood': 'Роузвуд', 'Riverside': 'Риверсайд',
    'WestPoint': 'Вест-Пойнт', 'MarchRidge': 'Марч-Ридж', 'Louisville': 'Луисвилл'}
TOWNS.update({'Brandenburg': 'Бранденбург', 'Ekron': 'Экрон', 'EchoCreek': 'Эхо-Крик', 'Irvington': 'Ирвингтон', 'FallasLake': 'Фаллас-Лейк', 'ValleyStation': 'Вэлли-Стейшн', 'LouisvilleAirport': 'Аэропорт Луисвилла'})


def death_lines(d, offset):
    if d is None:
        return ['Обстоятельства смерти: не записаны (смерть до обновления или нет данных).']
    cause = '; '.join(CAUSES.get(c, c) for c in d.cause.split(','))
    title = 'Причина смерти (предположительно): ' if d.certainty == 'probable' else 'Причина смерти: '
    lines = [title + cause]
    if d.certainty == 'probable':
        lines += ['Вывод по последнему состоянию; игра не подтвердила точную причину.']
    lines += ['Город смерти: ' + ('район ' + TOWNS.get(d.town, d.town) + ' (по области карты)' if d.town else 'не определён')]
    lines += ['Координаты смерти: ' + (f'X={d.position[0]}, Y={d.position[1]}, Z={d.position[2]}' if d.position is not None else 'не получены')]
    lines += ['Последние зарегистрированные раны:']
    for part in PARTS:
        if part in d.wounds:
            lines += ['  ' + PARTS[part] + ': ' + ', '.join(WOUNDS[f] for f in d.wounds[part])]
    if not d.wounds:
        lines += ['  Не обнаружены в снимке.' if d.known else '  Сведения не получены.']
    elif not d.known:
        lines += ['  Список неполный: часть показателей недоступна.']
    source = {'client': 'клиент игрока', 'server': 'сервер (данные могут быть неполными)', 'unknown': 'неизвестен'}[d.source]
    lines += ['Источник состояния: ' + source + '.', 'Снимок получен: ' + date(d.observed, offset)]
    if d.phase == 'stale':
        lines += ['Снимок устарел: раны могли измениться до смерти; причина по нему не определяется.']
    elif d.phase == 'recent':
        lines += ['Состояние незадолго до смерти; последняя рана могла не попасть в снимок.']
    return lines


def character_text(state, c, dates=True):
    status = 'жив' if c.alive else 'мёртв'
    text = [f'Персонаж «{c.name}» [№{c.id}] — {status}', f'Игрок: {c.user}',
            f'Всего: {duration(c.total)}', f'Сегодня: {duration(today(state, c))}',
            'Убито зомби: ' + (str(c.kills) if c.kills >= 0 else 'пока неизвестно')]
    if dates:
        text += ['Рождение:', '  Игровое: ' + date(c.born_game, real=False),
                 '  Реальное: ' + date(c.born_real, state.offset)]
        if c.alive:
            text += ['Живёт по дату отчёта:', '  Игровое: ' + date(state.game, real=False),
                     '  Реальное: ' + date(state.stamp, state.offset)]
        else:
            text += ['Смерть:', '  Игровое: ' + date(c.died_game, real=False),
                     '  Реальное: ' + date(c.died_real, state.offset)]
            text += death_lines(c.death, state.offset)
    names = {'toc': 'The Only Cure', 'cu': 'Casualties Undead'}
    if c.limb_provider == 'conflict':
        text += ['Конфликт: Casualties Undead + The Only Cure. Управление конечностями отключено.']
    elif c.limb_provider in names:
        text += ['Медицинский мод: ' + names[c.limb_provider]]
        text += ['Ампутации: ' + ((', '.join(PARTS[p] for p in limb_parts(c) if p in c.amputated) or 'нет')
                                if c.limbs_ready else 'данные пока недоступны')]
    if c.wounds:
        text += ['Медицинский мод: Wounds Overhaul']
    if c.observed:
        text += ['Показатели записаны: ' + date(c.observed, state.offset)]
    if c.online and c.client_status:
        shown = lambda v: 'не определена' if v in ('', '-') else v
        text += ['Liquidus на ПК: ' + shown(c.client_version),
                 'Модуль управления: ' + shown(c.remote_version) + ' · ' + shown(c.client_build)]
        if c.client_status == 'mismatch':
            text += ['Клиент нужно обновить целиком до 1.5.0.6.9 FIX1. Проверь /liquidusversion.']
        elif c.client_status in ('unknown', 'missing', 'stale'):
            text += ['Свежего подтверждения клиентского модуля нет. Подожди 5 секунд и обнови карточку.']
    if not state.fresh():
        text += ['Снимок устарел. Онлайн и показатели показаны на момент записи; управление недоступно.']
    elif c.online:
        text += ['Сейчас на сервере.']
    return '\n'.join(text)


class Buttons:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.values = {}

    def add(self, actor, title, kind, **data):
        now = self.clock()
        self.values = {k: v for k, v in self.values.items() if v['expires'] > now}
        while len(self.values) >= 2000:
            self.values.pop(next(iter(self.values)))
        key = secrets.token_urlsafe(12)
        self.values[key] = {'actor': actor, 'kind': kind, 'data': data, 'expires': now + 600}
        return {'text': title[:60], 'callback_data': key}

    def get(self, actor, key):
        b = self.values.get(key)
        if not b or b['actor'] != actor or b['expires'] <= self.clock():
            return None
        if b['kind'] in ('confirm', 'hostconfirm'):
            self.values.pop(key)  # Consume BEFORE any network operation.
        return b

    def retain(self, actor, keys):
        self.values = {k: v for k, v in self.values.items() if v['actor'] != actor or k in keys}


def restore_parts(character):
    """One highest missing segment per anatomical limb; CU restores it whole."""
    groups = [('UpperArm_' + side, 'ForeArm_' + side, 'Hand_' + side) for side in ('L', 'R')]
    if character.limb_provider == 'cu':
        groups += [('UpperLeg_' + side, 'LowerLeg_' + side, 'Foot_' + side) for side in ('L', 'R')]
    return [next(p for p in group if p in character.amputated)
            for group in groups if any(p in character.amputated for p in group)]


def text_pages(text, limit=3500):
    """Stay below Telegram's limit even for supplementary Unicode characters."""
    pages, lines, size = [], '', 0
    for line in (text or '—').splitlines(keepends=True):
        for char in line:
            units = 2 if ord(char) > 0xffff else 1
            if size + units > limit:
                pages.append(lines); lines, size = '', 0
            lines += char; size += units
    return pages + ([lines] if lines else [])
