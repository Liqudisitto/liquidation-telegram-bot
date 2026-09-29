import copy
import json
import time
import unittest
from unittest.mock import patch
import test_bot as base
from bot import Bot
from protocol import frame, snapshot, death_row, ProtocolError
from transport import ApiError, Panel
from ui import character_text, death_lines


class HostPanel(Panel):
    def __init__(self, config):
        super().__init__(config)
        self.state = {'state': 'offline', 'suspended': False, 'uptime': 0}
        self.allow = b'# owner\n123\n'
        self.calls, self.writes = [], []
        self.fail = None

    def api(self, endpoint, payload=None):
        self.calls.append(endpoint)
        if payload is None:
            return dict(self.state)
        self.writes.append((endpoint, payload))
        if self.fail:
            raise self.fail

    def call_file(self, suffix, content=None):
        self.calls.append(suffix)
        if suffix != 'admins' or content is not None:
            raise AssertionError('Host actions must not read/write game snapshots or requests')
        return self.allow

    def snapshot(self):
        raise AssertionError('Host menu must work without the game/mod running')


class HostMenuTests(unittest.TestCase):
    callback = base.BotTests.callback

    def setUp(self):
        base.BotTests.setUp(self)
        self.panel = HostPanel(self.config)
        self.bot = Bot(self.config, self.tg, self.panel)

    def press(self, text):
        key = next(b['callback_data'] for row in self.tg.history[-1][2] for b in row if b['text'] == text)
        self.callback(key)

    def preview(self, action='start'):
        self.bot.route(123, 'hostpreview', {'action': action, 'label': action})
        return self.tg.history[-1][2][0][0]['callback_data']

    def test_offline_section_in_main_menu_has_all_five_buttons_and_back(self):
        self.bot.command(123, '/menu');self.press('Ликвидус')
        text, keys = self.tg.history[-1][1:]
        captions = [b['text'] for row in keys for b in row]
        for title in ('Сохранение мира', 'Проверка апдейтов', 'Перезапуск Ликвидуса',
                      'Выключение Ликвидуса', 'Включение Ликвидуса', 'Главное меню'):
            self.assertIn(title, captions)
        self.assertIn('выключен', text)
        self.press('Главное меню')
        self.assertEqual(len(self.tg.sent), 1)
        self.assertEqual(self.panel.writes, [])

    def test_all_actions_use_exact_routes_once_and_return_same_message_to_liquidus(self):
        for action, state, endpoint, payload in [
            ('start', 'offline', 'power', {'signal':'start'}),
            ('stop', 'running', 'power', {'signal':'stop'}),
            ('restart', 'running', 'power', {'signal':'restart'}),
            ('save', 'running', 'command', {'command':'save'}),
            ('check', 'running', 'command', {'command':'checkModsNeedUpdate'})]:
            with self.subTest(action=action):
                self.panel.state['state'] = state
                before = len(self.panel.writes)
                key = self.preview(action)
                self.assertEqual(len(self.panel.writes), before)
                self.callback(key);self.callback(key)
                self.assertEqual(self.panel.writes[-1], (endpoint, payload))
                self.assertEqual(len(self.panel.writes), before+1)
                self.assertIn('Ликвидус', self.tg.history[-1][1])
                self.assertEqual(len(self.tg.sent), 1)

    def test_revoked_remote_allowlist_and_foreign_actor_cannot_execute(self):
        key = self.preview()
        self.panel.allow = b'456\n';self.callback(key)
        self.assertEqual(self.panel.writes, [])
        self.assertIn('remote_admins.txt', self.tg.history[-1][1])
        self.panel.allow = b'123\n';key = self.preview()
        self.callback(key, user=456);self.callback(key, chat_type='group')
        self.assertEqual(self.panel.writes, [])

    def test_confirmation_expiry_cancellation_and_state_change_prevent_write(self):
        key = self.preview()
        self.bot.buttons.values[key]['data']['offered'] = time.monotonic()-61
        self.callback(key)
        self.assertEqual(self.panel.writes, [])
        key = self.preview();self.panel.state['state'] = 'starting';self.callback(key)
        self.assertEqual(self.panel.writes, [])
        self.panel.state['state'] = 'offline';key = self.preview()
        self.bot.route(123, 'menu', {});self.callback(key)
        self.assertEqual(self.panel.writes, [])

    def test_timeout_never_retries_power_and_receipt_survives_refresh(self):
        self.panel.fail = ApiError('timeout')
        key = self.preview();self.callback(key)
        self.assertEqual(self.panel.writes, [('power', {'signal':'start'})])
        self.assertIn('Итог запроса неизвестен', self.tg.history[-1][1])
        self.bot.route(123, 'host', {})
        self.assertIn('Автоповтора нет', self.tg.history[-1][1])
        self.callback(key)
        self.assertEqual(len(self.panel.writes), 1)

    def test_http_forbidden_is_rejection_not_fake_success(self):
        self.panel.fail = ApiError('HTTP 403: права', 403)
        key = self.preview();self.callback(key)
        self.assertIn('HTTP 403', self.tg.history[-1][1])
        self.assertNotIn('Панель приняла', self.tg.history[-1][1])

    def test_suspended_server_and_restarted_container_are_not_controlled(self):
        self.panel.state['suspended'] = True
        with self.assertRaises(ApiError): self.preview()
        self.panel.state.update(suspended=False, state='running', uptime=50000)
        key = self.preview('restart');self.panel.state['uptime'] = 1000;self.callback(key)
        self.assertEqual(self.panel.writes, [])

    def test_menu_from_live_and_dead_character_card(self):
        state = base.FakePanel().state
        for died in (-1, 1000):
            state.chars[1].died_real = died
            self.bot.character(123, state, state.chars[1])
            self.press('Главное меню')
            self.assertIn('Ликвидус', [b['text'] for row in self.tg.history[-1][2] for b in row])
        self.assertEqual(len(self.tg.sent), 1)


class PanelHostTransportTests(unittest.TestCase):
    def setUp(self):
        self.panel = Panel(base.Config('unused', {123}, 'https://example.test', '12345678', 'PRIVATE'))

    def test_resource_and_power_json_and_timeouts_are_bounded(self):
        raw = json.dumps({'attributes': {'current_state':'offline', 'is_suspended':False, 'resources':{'uptime':0}}}).encode()
        with patch('transport.http', return_value=raw) as http:
            self.assertEqual(self.panel.api('resources')['state'], 'offline')
            self.assertTrue(http.call_args.args[0].endswith('/api/client/servers/12345678/resources'))
            self.assertIsNone(http.call_args.args[1])
            self.panel.api('power', {'signal':'start'})
            self.assertEqual(json.loads(http.call_args.args[1]), {'signal':'start'})
            self.assertEqual(http.call_args.kwargs['timeout'], 12)

    def test_allowlist_matches_lua_comments_and_rejects_bad_or_missing_file(self):
        for text in (b'123\n', b' # comment\n 123 \r\n'):
            with patch.object(self.panel, 'call_file', return_value=text):
                self.panel.host_allowed(123)
        for text in (b'', b'999\n', b'123\nnot-an-id', b'0123', b'123\n' + b'0'*4100, b'\xef\xbb\xbf123'):
            with patch.object(self.panel, 'call_file', return_value=text):
                with self.assertRaises(ApiError): self.panel.host_allowed(123)
        with patch.object(self.panel, 'call_file', side_effect=ApiError('offline')):
            with self.assertRaises(ApiError): self.panel.host_allowed(123)

    def test_unknown_actions_cannot_be_arbitrary_console_or_power_kill(self):
        s = {'state':'running', 'suspended':False, 'uptime':10}
        for action in ('kill', 'quit', 'stop\nsave', 'watchdog pause'):
            with self.assertRaises(ApiError): self.panel.host_ready(action, s)


class DeathDisplayTests(unittest.TestCase):
    def row(self):
        h = lambda v: v.encode().hex()
        return ['F','1','1790698000000','client','final','bleeding','probable','10650','9800','0',h('Muldraugh'),'1',h('Hand_L=bite,bandaged|Neck=bleeding')]

    def test_russian_parts_location_probable_cause_and_old_death_unknown(self):
        d = death_row(self.row());text = '\n'.join(death_lines(d, 180))
        for word in ('предположительно', 'кровотечение от ран', 'Левая кисть: укус, повязка', 'Шея: кровотечение', 'район Малдро', 'X=10650'):
            self.assertIn(word, text)
        self.assertIn('не записаны', '\n'.join(death_lines(None, 180)))

    def test_malformed_and_unknown_wound_flags_are_rejected(self):
        for index, value in [(7, 'nan'), (7, '1.5'), (8, '-'), (9, '999'), (6, 'confirmed'),
                             (12, 'Head=magic'.encode().hex())]:
            row = self.row();row[index] = value
            with self.assertRaises(ValueError): death_row(row)

    def test_fatality_row_cannot_mark_a_living_character_dead(self):
        h = lambda v: v.encode().hex()
        wire = frame([['LPRS1','boot',1790698000000,742310000,'1.4.2.6.9',180,1,'2026-09-29'],
                      ['C',1,h('User'),h('Name'),0,0,0,0,-1,-1,100,100,'session'],self.row()])
        with self.assertRaises(ProtocolError): snapshot(wire)


if __name__ == '__main__':
    unittest.main()
