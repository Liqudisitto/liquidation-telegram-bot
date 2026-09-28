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
    'scratch': 'Царапина', 'cut': 'Рваная рана', 'amputate': 'Ампутация',
    'restore': 'Восстановить конечность',
    'setskill': 'Изменение навыка', 'transfer': 'Перенос навыков'}
REASONS = {
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
    'client_adapter_unavailable': 'На клиенте отсутствует нужная версия мода или адаптера Wounds.',
    'admin_revoked': 'Во время операции доступ администратора был отозван.',
    'response_timeout': 'Подтверждение не получено. Проверь персонажа и журнал перед повтором.',
    'delivery_unknown': 'Неизвестно, дошёл ли запрос. Проверь персонажа и журнал перед повтором.',
    'client_timeout_check_player': 'Клиент не ответил вовремя. Проверь персонажа и журнал.',
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
    if c.toc == 'ready':
        text += ['Ампутации: ' + (', '.join(PARTS.get(p, p) for p in LIMBS if p in c.amputated) or 'нет')]
    else:
        text += ['The Only Cure: ' + ('не установлен' if c.toc == 'absent' else 'данные пока недоступны')]
    if c.observed:
        text += ['Показатели записаны: ' + date(c.observed, state.offset)]
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
        if b['kind'] == 'confirm':
            self.values.pop(key)  # Consume BEFORE any network operation.
        return b

    def retain(self, actor, keys):
        self.values = {k: v for k, v in self.values.items() if v['actor'] != actor or k in keys}


def restore_parts(character):
    """Only offer the highest missing segment per side: no floating hands."""
    return [next(p for p in ('UpperArm_' + side, 'ForeArm_' + side, 'Hand_' + side)
                 if p in character.amputated)
            for side in ('L', 'R') if any(p.endswith('_' + side) for p in character.amputated)]


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
