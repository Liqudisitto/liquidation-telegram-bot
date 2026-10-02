"""Bounded ASCII transport shared with Liquidation's Lua bridge."""
from dataclasses import dataclass, field
import math
import re
import time
import zlib

VERSION = '1.6.0.6.9'
BUILD = 'R1'
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


DEATH_PARTS = ('Hand_L', 'Hand_R', 'ForeArm_L', 'ForeArm_R', 'UpperArm_L', 'UpperArm_R',
    'Torso_Upper', 'Torso_Lower', 'Head', 'Neck', 'Groin', 'UpperLeg_L', 'UpperLeg_R',
    'LowerLeg_L', 'LowerLeg_R', 'Foot_L', 'Foot_R')
WOUND_FLAGS = ('bite', 'scratch', 'cut', 'deep', 'bleeding', 'burn', 'fracture', 'bullet',
               'glass', 'infected', 'bandaged', 'stitched')
DEATH_CAUSES = ('unknown', 'admin_kill', 'knox', 'bleeding', 'blood_loss', 'sepsis', 'fire')


@dataclass
class Death:
    observed: int
    source: str
    phase: str
    cause: str
    certainty: str
    position: tuple | None
    town: str
    known: bool
    wounds: dict


def death_row(a):
    if len(a) != 13 or a[0] != 'F':
        raise ValueError()
    observed = int(a[2])
    if not 0 <= observed <= 9007199254740991 or a[3] not in ('client', 'server', 'unknown') or a[4] not in ('final', 'recent', 'stale', 'unavailable'):
        raise ValueError()
    causes = a[5].split(',')
    if (len(set(causes)) != len(causes) or any(c not in DEATH_CAUSES for c in causes)
            or a[6] not in ('unknown', 'probable', 'confirmed') or a[11] not in ('0', '1')):
        raise ValueError()
    if ((a[5] == 'unknown') != (a[6] == 'unknown') or (a[5] == 'admin_kill') != (a[6] == 'confirmed')
            or ('unknown' in causes and a[5] != 'unknown') or ('admin_kill' in causes and a[5] != 'admin_kill')):
        raise ValueError()
    position = None
    if a[7:10] != ['-', '-', '-']:
        position = tuple(map(int, a[7:10]))
        if any(abs(n) > 10000000 for n in position[:2]) or abs(position[2]) > 100:
            raise ValueError()
    town, raw = unhex(a[10]), unhex(a[12])
    if len(town.encode('utf-8')) > 128 or len(raw) > 2600:
        raise ValueError()
    wounds = {}
    for line in raw.split('|') if raw else []:
        part, flags = line.split('=')
        values = flags.split(',')
        if part not in DEATH_PARTS or part in wounds or len(set(values)) != len(values) or any(f not in WOUND_FLAGS for f in values):
            raise ValueError()
        wounds[part] = values
    return Death(observed, a[3], a[4], a[5], a[6], position, town, a[11] == '1', wounds)


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
    death: Death | None = None
    provider: str = ''
    limb_status: str = ''
    wounds: bool = False
    client_version: str = ''
    remote_version: str = ''
    client_build: str = ''
    client_status: str = ''
    injuries: dict = field(default_factory=dict)
    injuries_at: int = 0
    injuries_known: bool = False

    def fresh_injuries(self, now=None):
        age = (time.time() if now is None else now) * 1000 - self.injuries_at
        return self.injuries_known and -2000 <= age <= 15000

    @property
    def limb_provider(self):
        # Optional M row: pre-1.5 offline histories retain their TOC identity.
        return self.provider or ('toc' if self.toc != 'absent' else 'none')

    @property
    def limbs_ready(self):
        return self.limb_provider in ('toc', 'cu') and (self.limb_status or self.toc) == 'ready'


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
    build: str = ''

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
            if a[0] == 'B' and len(a) == 2:
                if out.build or not re.fullmatch(r'[A-Za-z0-9_.-]{1,32}', a[1]):
                    raise ValueError()
                out.build = a[1]
            elif a[0] == 'C' and len(a) == 13:
                cid = int(a[1])
                if cid in out.chars or cid < 1:
                    raise ValueError()
                out.chars[cid] = Character(cid, unhex(a[2]), unhex(a[3]),
                    *map(int, a[4:12]), a[12])
            elif a[0] == 'F':
                c = out.chars[int(a[1])]
                if c.alive or c.death is not None:
                    raise ValueError()
                c.death = death_row(a)
            elif a[0] == 'E' and len(a) == 8:
                c = out.chars[int(a[1])]
                c.observed, c.kills, c.health = map(int, a[2:5])
                c.toc = a[5]
                c.amputated = set(filter(None, unhex(a[6]).split(',')))
                c.skills_at = int(a[7])
            elif a[0] == 'M' and len(a) == 5:
                c = out.chars[int(a[1])]
                if (c.provider or a[2] not in ('none', 'toc', 'cu', 'conflict')
                        or a[3] not in ('ready', 'pending', 'absent', 'error', 'conflict')
                        or a[4] not in ('0', '1')
                        or (a[2] == 'conflict') != (a[3] == 'conflict')
                        or (a[2] == 'none') != (a[3] == 'absent')):
                    raise ValueError()
                c.provider, c.limb_status, c.wounds = a[2], a[3], a[4] == '1'
            elif a[0] == 'J' and len(a) == 5:
                c = out.chars[int(a[1])]
                stamp = int(a[2])
                raw = unhex(a[4])
                if (not c.online or c.injuries_at or a[3] not in ('0', '1')
                        or not 1 <= stamp <= out.stamp or len(raw) > 2600):
                    raise ValueError()
                injuries = {}
                for line in raw.split('|') if raw else []:
                    part, flags = line.split('=')
                    values = flags.split(',')
                    if (part not in DEATH_PARTS or part in injuries or len(set(values)) != len(values)
                            or any(f not in WOUND_FLAGS[:10] for f in values)):
                        raise ValueError()
                    injuries[part] = values
                c.injuries, c.injuries_at, c.injuries_known = injuries, stamp, a[3] == '1'
            elif a[0] == 'V' and len(a) == 6:
                c = out.chars[int(a[1])]
                if (c.client_status or not c.online
                        or any(not re.fullmatch(r'[A-Za-z0-9_.-]{1,32}', s) for s in a[2:5])
                        or a[5] not in ('unknown', 'missing', 'mismatch', 'stale', 'ready')):
                    raise ValueError()
                c.client_version, c.remote_version, c.client_build, c.client_status = a[2:]
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
