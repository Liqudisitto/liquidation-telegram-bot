"""Read a fresh native Workshop result. Never replay a console command."""
import json
import importlib
import re
import time
from urllib.parse import urlsplit


class WorkshopError(RuntimeError):
    pass


def websocket_backend():
    # Ship the pinned, unmodified pure-Python library with the bot. BotHost
    # file updates can leave an old environment even with requirements.txt
    # present. No pip subprocess, network install or global sys.path change.
    for module_name, source in (('_vendor.websocket', 'bundled'), ('websocket', 'installed')):
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            continue
        if (getattr(module, '__version__', None) == '1.9.0'
                and callable(getattr(module, 'create_connection', None))):
            return module.create_connection, 'websocket-client 1.9.0 (' + source + ')'
    raise WorkshopError('Не найден websocket-client 1.9.0. Скопируй папку _vendor из нового архива '
                        'рядом с main.py и перезапусти бота, либо пересобери его с requirements.txt.')


RESULTS = {
    'Mods updated': 'Моды Workshop актуальны. Обновление не требуется.',
    'Mods need update': 'Найдены обновления модов Workshop. Требуется обновление сервера.',
    'Check not completed': 'Игра не смогла завершить проверку Workshop. Актуальность модов неизвестна.',
}
ANSI = re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]')
PREFIX = r'LOG\s*:\s*{}\s+f:\s*[\d,]+\s+st:\s*[\d,]+>\s*'
CHECK = re.compile(PREFIX.format('Mod') + r'CheckModsNeedUpdate:\s*(Checking\.\.\.|Mods updated|Mods need update|Check not completed)\s*$')
ECHO = re.compile(PREFIX.format('General') + r'command entered via server console \(System\.in\): "checkModsNeedUpdate"\s*$')


class ResultParser:
    def __init__(self):
        self.echo = False
        self.started = False
        self.overlap = False

    def feed(self, text):
        # Wings console events normally contain one line; multiline events work
        # too. Unrelated chat/quoted result strings cannot satisfy fullmatch.
        for line in ANSI.sub('', text).splitlines():
            line = line.strip()
            if ECHO.fullmatch(line):
                if self.echo:
                    self.overlap = True
                self.echo = True
                continue
            match = CHECK.fullmatch(line)
            if not match or not self.echo:
                continue
            status = match[1]
            if status == 'Checking...':
                if self.started:
                    self.overlap = True
                self.started = True
            elif self.started and not self.overlap:
                return 'CheckModsNeedUpdate: ' + status + '\n' + RESULTS[status]
        return None


class WorkshopConsole:
    def __init__(self, endpoint, token, origin, connector=None, clock=time.monotonic):
        u = urlsplit(endpoint)
        if (u.scheme != 'wss' or not u.hostname or u.username or u.password or u.query or u.fragment
                or not re.fullmatch(r'/api/servers/[A-Za-z0-9-]{8,64}/ws', u.path)
                or not isinstance(token, str) or not 1 <= len(token) <= 16384):
            raise WorkshopError('Панель вернула неподдерживаемый адрес консоли. Нужен защищённый WSS.')
        if connector is None:
            connector, _ = websocket_backend()
        self.clock = clock
        self.socket = None
        try:
            # Panel bearer key never goes to Wings. WSS certificate validation
            # stays enabled; redirects are forbidden to protect the socket JWT.
            self.socket = connector(endpoint, timeout=8, origin=origin, redirect_limit=0)
            if self.socket.getstatus() != 101:
                raise WorkshopError('Консоль не подтвердила WebSocket-соединение. Перенаправления не поддерживаются.')
            self.socket.send(json.dumps({'event': 'auth', 'args': [token]}))
            deadline, authenticated = clock() + 10, False
            while clock() < deadline:
                event, args = self.receive(deadline)
                if event == 'auth success':
                    authenticated = True
                elif event == 'status' and authenticated:
                    if args != ['running']:
                        raise WorkshopError('Игровой сервер сейчас не запущен.')
                    return
            raise WorkshopError('Консоль не подтвердила подключение. Проверь websocket.connect в панели.')
        except WorkshopError:
            self.close()
            raise
        except Exception:
            self.close()
            raise WorkshopError('Не удалось подключиться к консоли EGNetwork по WSS. Проверь доступ и websocket.connect.') from None

    def receive(self, deadline):
        self.socket.settimeout(max(0.05, min(1, deadline - self.clock())))
        try:
            raw = self.socket.recv()
        except TimeoutError:
            return '', []
        except Exception as error:
            # websocket-client has its own timeout type; no error text may
            # escape, because handshakes can contain tokens and server URLs.
            if type(error).__name__ == 'WebSocketTimeoutException':
                return '', []
            raise WorkshopError('Соединение с консолью прервалось. Итог проверки неизвестен.') from None
        if not raw:
            raise WorkshopError('Консоль закрыла соединение. Итог проверки неизвестен.')
        try:
            if len(raw) > 262144:
                raise ValueError()
            message = json.loads(raw)
            event, args = message.get('event'), message.get('args', [])
            if not isinstance(event, str) or not isinstance(args, list) or any(not isinstance(a, str) for a in args):
                raise ValueError()
            if event in ('jwt error', 'token expired', 'daemon error'):
                raise WorkshopError('Консоль отклонила доступ. Проверь права ключа и состояние сервера.')
            return event, args
        except (ValueError, TypeError, AttributeError):
            raise WorkshopError('Консоль вернула неподдерживаемое сообщение.') from None

    def drain(self):
        # Throw away lines already waiting before dispatch. Never request logs
        # or accept a saved historic "Mods updated" as the result of this check.
        deadline = self.clock() + 0.25
        while self.clock() < deadline:
            self.receive(deadline)

    def result(self):
        deadline, parser = self.clock() + 40, ResultParser()
        while self.clock() < deadline:
            event, args = self.receive(deadline)
            if event == 'console output':
                for chunk in args:
                    found = parser.feed(chunk)
                    if found:
                        return found
            elif event == 'status' and args in (['offline'], ['stopping']):
                return 'Сервер остановился во время проверки. Результат CheckModsNeedUpdate не получен.'
        if parser.overlap:
            return 'В консоли пересеклись несколько проверок Workshop. Однозначный результат не получен; повтори позже.'
        return 'Результат CheckModsNeedUpdate не получен за 40 секунд. Это не означает, что моды актуальны. Проверь консоль; автоповтора нет.'

    def close(self):
        if self.socket is not None:
            try:
                self.socket.close(timeout=1)
            except Exception:
                pass
            self.socket = None
