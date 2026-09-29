"""HTTPS only; no token-bearing URLs or response bodies in exceptions/logs."""
from dataclasses import dataclass
import json
import os
import posixpath
import re
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from protocol import MAX_BYTES, ProtocolError, snapshot, rows, request


class ApiError(RuntimeError):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class TelegramError(ApiError):
    def __init__(self, reason):
        self.reason = reason
        super().__init__('Telegram не выполнил запрос. Открой /menu или попробуй позже.')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def http(url, body=None, headers=None, timeout=35, cap=MAX_BYTES, telegram_errors=False):
    req = urllib.request.Request(url, data=body, headers=headers or {})
    try:
        with urllib.request.build_opener(NoRedirect()).open(req, timeout=timeout) as response:
            data = response.read(cap + 1)
            if len(data) > cap:
                raise ApiError('Ответ сервиса превышает допустимый размер.')
            return data
    except urllib.error.HTTPError as error:
        if telegram_errors and error.code == 400:
            # Telegram describes edit errors in a JSON body even on HTTP 400.
            # Only Telegram.call classifies it; the body never enters a log.
            with error:
                data = error.read(cap + 1)
            if len(data) <= cap:
                return data
        if error.code == 404:
            raise ApiError('HTTP 404: проверь адрес панели, Server ID и путь к файлам мода.', 404) from None
        if error.code in (401, 403):
            raise ApiError('HTTP 401/403: проверь ключ и права доступа.', error.code) from None
        if error.code == 429:
            raise ApiError('HTTP 429: сервис ограничил запросы. Подожди немного.', error.code) from None
        raise ApiError(f'HTTP {error.code}: сервис отклонил запрос.', error.code) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ApiError('Нет ответа HTTPS-сервиса. Проверь соединение и настройки.') from None


@dataclass
class Config:
    token: str
    admins: set
    panel: str
    server: str
    key: str
    cache: str = '/.cache/Lua'
    prefix: str = 'LiquidusPlaytime_Liquidus_'

    @classmethod
    def environment(cls):
        token = os.getenv('BOT_TOKEN') or os.getenv('TELEGRAM_BOT_TOKEN') or ''
        if not re.fullmatch(r'\d+:[A-Za-z0-9_-]{20,}', token):
            raise ApiError('Задай BOT_TOKEN в BotHost.')
        raw = os.getenv('ADMIN_IDS', '').strip()
        if raw and not re.fullmatch(r'[1-9]\d*(?:\s*,\s*[1-9]\d*)*', raw):
            raise ApiError('ADMIN_IDS: числовые Telegram ID через запятую.')
        return cls(token, {int(x.strip()) for x in raw.split(',') if x.strip()},
                   os.getenv('PZ_PANEL_URL', '').rstrip('/'), os.getenv('PZ_SERVER_ID', ''),
                   os.getenv('PZ_API_KEY', ''), os.getenv('PZ_CACHE_LUA', '/.cache/Lua'),
                   os.getenv('PZ_PREFIX', 'LiquidusPlaytime_Liquidus_'))

    def validate_panel(self):
        u = urllib.parse.urlsplit(self.panel)
        if u.scheme != 'https' or not u.hostname or u.username or u.password or u.query or u.fragment:
            raise ApiError('Задай PZ_PANEL_URL: HTTPS-адрес панели EGNetwork.')
        if not re.fullmatch(r'[A-Za-z0-9-]{8,64}', self.server) or not self.key:
            raise ApiError('Задай PZ_SERVER_ID и клиентский PZ_API_KEY в BotHost.')
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', self.prefix):
            raise ApiError('Недопустимый PZ_PREFIX.')
        if not self.cache.startswith('/') or '..' in self.cache.split('/'):
            raise ApiError('Недопустимый PZ_CACHE_LUA.')


class Panel:
    def __init__(self, config):
        self.config = config

    def api(self, endpoint, payload=None):
        if endpoint not in ('resources', 'command', 'power'):
            raise ApiError('Неизвестная операция панели.')
        c = self.config
        c.validate_panel()
        raw = http(c.panel + '/api/client/servers/' + c.server + '/' + endpoint,
            None if payload is None else json.dumps(payload).encode('utf-8'),
            {'Authorization': 'Bearer ' + c.key, 'Accept': 'Application/vnd.pterodactyl.v1+json',
             'Content-Type': 'application/json'}, timeout=12, cap=65536)
        if payload is not None:
            return None  # HTTP acceptance is not proof of a saved world/completed restart.
        try:
            data = json.loads(raw)
            a = data['attributes']
            if a['current_state'] not in ('running', 'starting', 'stopping', 'offline'):
                raise ValueError()
            if not isinstance(a['is_suspended'], bool):
                raise ValueError()
            uptime = a.get('resources', {}).get('uptime')
            if uptime is not None and (type(uptime) not in (int, float) or not 0 <= uptime <= 10**15):
                raise ValueError()
            return {'state': a['current_state'], 'suspended': a['is_suspended'], 'uptime': uptime}
        except (ValueError, TypeError, KeyError, AttributeError):
            raise ApiError('Панель вернула неизвестный формат состояния сервера.') from None

    def host_allowed(self, actor):
        # The game can be offline: read the same server-side allowlist directly.
        # No fallback to ADMIN_IDS alone if the file cannot be read.
        if type(actor) is not int or actor not in self.config.admins:
            raise ApiError('Доступ к управлению Ликвидусом закрыт.')
        try:
            raw = self.call_file('admins')
            if len(raw) > 4096:
                raise ValueError()
            allowed = set()
            for line in raw.decode('utf-8').splitlines():
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if not re.fullmatch(r'[1-9][0-9]{0,19}', line):
                    raise ValueError()
                allowed.add(int(line))
        except (UnicodeError, ValueError):
            raise ApiError('Проверь формат remote_admins.txt: один Telegram ID на строку, UTF-8 без BOM.') from None
        if actor not in allowed:
            raise ApiError('Твой Telegram ID не указан в remote_admins.txt на игровом сервере.')

    @staticmethod
    def host_ready(action, status):
        if action not in ('save', 'check', 'restart', 'stop', 'start'):
            raise ApiError('Неизвестное действие Ликвидуса.')
        if status['suspended']:
            raise ApiError('Хостинг приостановил сервер. Проверь панель EGNetwork.')
        expected = 'offline' if action == 'start' else 'running'
        if status['state'] != expected:
            raise ApiError('Для включения сервер должен быть выключен; для остальных действий — запущен. Обнови состояние.')

    def host_action(self, actor, action, preview):
        self.host_allowed(actor)
        current = self.api('resources')
        self.host_ready(action, current)
        if current['state'] != preview['state'] or (current['uptime'] is not None
                and preview.get('uptime') is not None and current['uptime'] < preview['uptime']):
            raise ApiError('Состояние сервера изменилось после подтверждения. Выбери действие заново.')
        endpoint = 'command' if action in ('save', 'check') else 'power'
        payload = {'command': {'save': 'save', 'check': 'checkModsNeedUpdate'}[action]} if endpoint == 'command' else {'signal': action}
        try:
            self.api(endpoint, payload)
        except ApiError as error:
            if error.status is not None and 400 <= error.status < 500:
                raise
            # A timeout/5xx can happen after the command reached Wings.
            # Do not retry a power operation or send an alternative console command.
            return 'Итог запроса неизвестен. Автоповтора нет. Проверь состояние и консоль EGNetwork перед повтором.'
        return {
            'save': 'Панель приняла команду save. Завершение сохранения проверь в консоли сервера.',
            'check': 'CheckModsNeedUpdate: команда принята панелью. Результат проверки модов смотри в консоли и игровом чате. Это проверка Workshop, не обновление версии игры.',
            'restart': 'Панель приняла сигнал перезапуска. Дождись загрузки мира; состояние «запущен» относится к процессу в панели.',
            'stop': 'Панель приняла сигнал обычной остановки. Обнови состояние через несколько секунд.',
            'start': 'Панель приняла сигнал запуска. Загрузка мира и модов может занять несколько минут.'
        }[action]

    def call_file(self, suffix, content=None):
        c = self.config
        c.validate_panel()
        path = posixpath.join(c.cache, c.prefix + 'remote_' + suffix + '.txt')
        method = 'contents' if content is None else 'write'
        url = (c.panel + '/api/client/servers/' + c.server + '/files/' + method + '?' +
               urllib.parse.urlencode({'file': path}))
        return http(url, content, {'Authorization': 'Bearer ' + c.key,
                    'Accept': 'Application/vnd.pterodactyl.v1+json', 'Content-Type': 'text/plain'}, timeout=12)

    def snapshot(self):
        found, errors = [], []
        for slot in ('a', 'b'):
            try:
                found.append(snapshot(self.call_file('snapshot_' + slot)))
            except (ApiError, ProtocolError) as error:
                errors.append(str(error))
        if not found:
            raise ApiError(errors[0] + ' Мод 1.4.2.6.9 должен быть запущен на игровом сервере.')
        return max(found, key=lambda x: x.stamp)

    def execute(self, actor, state, character, action, argument):
        rid = secrets.token_hex(16)
        uncertain = False
        try:
            self.call_file('request', request(rid, state, actor, character, action, argument))
        except ApiError:
            # A timed-out POST may already have reached the panel. Never issue
            # a second command with a new ID; query the receipt instead.
            uncertain = True
        deadline = time.monotonic() + 27
        while time.monotonic() < deadline:
            time.sleep(1.5)
            try:
                a = rows(self.call_file('response'), 4096)
                if len(a) == 1 and len(a[0]) == 6 and a[0][0] == 'LPRR1' and a[0][1] == rid:
                    return a[0][4], a[0][5], rid
            except (ApiError, ProtocolError):
                pass
        return 'unknown', 'delivery_unknown' if uncertain else 'response_timeout', rid

    def journal(self):
        result = rows(self.call_file('journal'), 1024 * 1024)
        if result[0] != ['LPRJ1']:
            raise ProtocolError('Журнал не распознан.')
        return [r for r in result[1:] if len(r) == 9][-15:]


class Telegram:
    def __init__(self, token):
        self.base = 'https://api.telegram.org/bot' + token + '/'

    def call(self, method, **data):
        try:
            result = json.loads(http(self.base + method,
                json.dumps(data, ensure_ascii=False).encode(), {'Content-Type': 'application/json'},
                timeout=35, telegram_errors=True))
        except (ValueError, UnicodeError):
            raise ApiError('Некорректный ответ Telegram.') from None
        if not result.get('ok'):
            description = str(result.get('description', '')).lower()
            reason = 'failed'
            if result.get('error_code') == 400:
                if 'message is not modified' in description:
                    reason = 'not_modified'
                elif 'message to edit not found' in description or "message can't be edited" in description:
                    reason = 'not_editable'
            raise TelegramError(reason)
        return result.get('result')

    def send(self, chat, text, buttons=None):
        # The UI paginates first. Plain text avoids markup injection by names.
        return self.call('sendMessage', chat_id=chat, text=text or '—',
                         reply_markup={'inline_keyboard': buttons or []})

    def edit(self, chat, message_id, text, buttons=None):
        try:
            return self.call('editMessageText', chat_id=chat, message_id=message_id,
                text=text or '—', reply_markup={'inline_keyboard': buttons or []})
        except TelegramError as error:
            if error.reason == 'not_modified':
                return {'message_id': message_id}
            raise
