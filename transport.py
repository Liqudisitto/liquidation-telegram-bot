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
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def http(url, body=None, headers=None, timeout=35, cap=MAX_BYTES):
    req = urllib.request.Request(url, data=body, headers=headers or {})
    try:
        with urllib.request.build_opener(NoRedirect()).open(req, timeout=timeout) as response:
            data = response.read(cap + 1)
            if len(data) > cap:
                raise ApiError('Ответ сервиса превышает допустимый размер.')
            return data
    except urllib.error.HTTPError as error:
        if error.code == 404:
            raise ApiError('HTTP 404: проверь адрес панели, Server ID и путь к файлам мода.') from None
        if error.code in (401, 403):
            raise ApiError('HTTP 401/403: проверь ключ и права доступа.') from None
        if error.code == 429:
            raise ApiError('HTTP 429: сервис ограничил запросы. Подожди немного.') from None
        raise ApiError(f'HTTP {error.code}: сервис отклонил запрос.') from None
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
            raise ApiError(errors[0] + ' Мод 1.4.0 должен быть запущен на игровом сервере.')
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
                json.dumps(data, ensure_ascii=False).encode(), {'Content-Type': 'application/json'}, timeout=35))
        except (ValueError, UnicodeError):
            raise ApiError('Некорректный ответ Telegram.') from None
        if not result.get('ok'):
            raise ApiError('Telegram не выполнил запрос.')
        return result.get('result')

    def send(self, chat, text, buttons=None):
        # Plain text avoids Markdown/HTML injection from game names.
        chunks = []
        for line in text.splitlines(keepends=True):
            while len(line) > 3500:
                chunks.append(line[:3500]); line = line[3500:]
            if chunks and len(chunks[-1]) + len(line) <= 3500:
                chunks[-1] += line
            else:
                chunks.append(line)
        for i, chunk in enumerate(chunks or ['—']):
            args = {'chat_id': chat, 'text': chunk}
            if i == len(chunks) - 1 and buttons:
                args['reply_markup'] = {'inline_keyboard': buttons}
            self.call('sendMessage', **args)
