"""Bounded ASCII transport shared with Liquidation's Lua bridge."""
from dataclasses import dataclass, field
import math
import time
import zlib

VERSION = '1.4.1'
MAX_BYTES = 16 * 1024 * 1024


class ProtocolError(ValueError):
    pass


def frame(rows):
    body = ''.join('\t'.join(map(str, row)) + '\n' for row in rows).encode('ascii')
    return body + f'END\t{zlib.adler32(body)}\n'.encode('ascii')


def rows(data, cap=MAX_BYTES):
    if not isinstance(data, bytes) or len(data) > cap:
        raise ProtocolError('Размер файла обмена недопустим.')
    try:
        body, end = data.rsplit(b'END\t', 1)
        if not body.endswith(b'\n') or end != str(zlib.adler32(body)).encode() + b'\n':
            raise ValueError()
        return [line.split('\t') for line in body.decode('ascii').splitlines()]
    except (ValueError, UnicodeError):
        raise ProtocolError('Файл обмена ещё записывается или повреждён.') from None


def unhex(value):
    try:
        result = bytes.fromhex(value).decode('utf-8')
        if any(ord(c) < 32 or ord(c) == 127 for c in result):
            raise ValueError()
        return result
    except (ValueError, UnicodeError):
        raise ProtocolError('Некорректная строка в файле обмена.') from None


@dataclass
class Skill:
    id: str
    name: str
    level: int
    xp: float


@dataclass
class Character:
    id: int
    user: str
    name: str
    first_real: int
    first_game: int
    born_real: int
    born_game: int
    died_real: int
    died_game: int
    total: int
    today: int
    session: str
    observed: int = 0
    kills: int = -1
    health: int = -1
    toc: str = 'pending'
    amputated: set = field(default_factory=set)
    skills_at: int = 0
    skills: dict = field(default_factory=dict)

    @property
    def alive(self):
        return self.died_real < 0

    @property
    def online(self):
        return self.session != '-' and self.alive


@dataclass
class Snapshot:
    boot: str
    stamp: int
    game: int
    version: str
    offset: int
    enabled: bool
    day: str
    chars: dict

    def fresh(self, now=None):
        age = (time.time() if now is None else now) * 1000 - self.stamp
        return -10000 <= age <= 20000


def snapshot(data):
    try:
        all_rows = rows(data)
        h = all_rows[0]
        if len(h) != 8 or h[0] != 'LPRS1' or h[6] not in ('0', '1'):
            raise ValueError()
        out = Snapshot(h[1], int(h[2]), int(h[3]), h[4], int(h[5]), h[6] == '1', h[7], {})
        for a in all_rows[1:]:
            if a[0] == 'C' and len(a) == 13:
                cid = int(a[1])
                if cid in out.chars or cid < 1:
                    raise ValueError()
                out.chars[cid] = Character(cid, unhex(a[2]), unhex(a[3]),
                    *map(int, a[4:12]), a[12])
            elif a[0] == 'E' and len(a) == 8:
                c = out.chars[int(a[1])]
                c.observed, c.kills, c.health = map(int, a[2:5])
                c.toc = a[5]
                c.amputated = set(filter(None, unhex(a[6]).split(',')))
                c.skills_at = int(a[7])
            elif a[0] == 'K' and len(a) == 6:
                c = out.chars[int(a[1])]
                s = Skill(unhex(a[2]), unhex(a[3]), int(a[4]), float(a[5]))
                if s.id in c.skills or not 0 <= s.level <= 10 or not math.isfinite(s.xp) or s.xp < 0:
                    raise ValueError()
                c.skills[s.id] = s
            else:
                raise ValueError()
        return out
    except (ValueError, KeyError, IndexError, TypeError):
        raise ProtocolError('Не удалось прочитать статистику: проверь версию мода и целостность файлов.') from None


def request(rid, state, actor, character, action, argument='-'):
    return frame([['LPRQ1', rid, state.boot, state.stamp, actor, action,
                   character.id, character.session, argument, 'CONFIRM']])
