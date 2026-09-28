import copy
import time
import unittest
from unittest.mock import patch
from bot import Bot
from protocol import Character, ProtocolError, Skill, Snapshot, frame, rows, snapshot
from transport import Config, Panel, ApiError, NoRedirect
from ui import Buttons, duration


class FakeTelegram:
    def __init__(self):
        self.sent = []
        self.calls = []

    def send(self, *a):
        self.sent.append(a)

    def call(self, *a, **k):
        self.calls.append((a, k))


class FakePanel:
    def __init__(self):
        stamp = int(time.time()*1000)
        self.state = Snapshot('boot-1', stamp, 742310000, '1.4.0', 180, True, '2026-09-28', {})
        c = Character(1, 'User', 'Живой <персонаж>', stamp, 742310000, stamp, 742310000, -1, -1, 10000, 10000, 'session-1')
        c.skills = {'Woodwork': Skill('Woodwork', 'Carpentry', 3, 940.25)}
        c.skills_at = stamp
        self.state.chars[1] = c
        self.sent = []
        self.reads = 0

    def snapshot(self):
        self.reads += 1
        return self.state

    def execute(self, *a):
        self.sent.append(a)
        return 'ok', 'skills_updated', 'abc'


class BotTests(unittest.TestCase):
    def setUp(self):
        self.config = Config('unused', {123}, 'https://example.test', '12345678', 'private')
        self.tg, self.panel = FakeTelegram(), FakePanel()
        self.bot = Bot(self.config, self.tg, self.panel)

    def callback(self, key, user=123, chat_type='private'):
        self.bot.update({'callback_query': {'id': 'call', 'from': {'id': user}, 'data': key,
            'message': {'chat': {'id': user, 'type': chat_type}}}})

    def confirm_button(self, action='kill', arg='-'):
        self.bot.preview(123, self.panel.state, self.panel.state.chars[1], action, arg)
        return self.tg.sent[-1][2][0][0]['callback_data']

    def test_unauthorized_actor_never_reads_game_data(self):
        self.bot.update({'message': {'from': {'id': 999}, 'chat': {'id': 999, 'type': 'private'}, 'text': '/start'}})
        self.assertEqual(self.panel.reads, 0)
        self.assertEqual(self.panel.sent, [])

    def test_admin_in_group_cannot_control(self):
        self.callback(self.confirm_button(), chat_type='group')
        self.assertEqual(self.panel.sent, [])

    def test_callback_is_bound_to_authenticated_actor(self):
        self.config.admins.add(456)
        self.callback(self.confirm_button(), user=456)
        self.assertEqual(self.panel.sent, [])

    def test_confirm_is_single_use_even_if_delivered_twice(self):
        key = self.confirm_button()
        self.callback(key); self.callback(key)
        self.assertEqual(len(self.panel.sent), 1)

    def test_server_restart_or_respawn_invalidates_confirmation(self):
        for change in ('boot', 'session'):
            key = self.confirm_button()
            if change == 'boot':
                self.panel.state.boot += '-new'
            else:
                self.panel.state.chars[1].session += '-new'
            self.callback(key)
        self.assertEqual(self.panel.sent, [])

    def test_stale_snapshot_and_disabled_bridge_block_actions(self):
        key = self.confirm_button()
        self.panel.state.stamp -= 60000
        self.callback(key)
        self.assertEqual(self.panel.sent, [])
        self.panel.state.stamp = int(time.time()*1000)
        key = self.confirm_button()
        self.panel.state.enabled = False
        self.callback(key)
        self.assertEqual(self.panel.sent, [])

    def test_set_skill_hex_encodes_id_and_has_explicit_confirmation(self):
        key = self.confirm_button('setskill', 'Woodwork:0')
        self.assertEqual(self.panel.sent, [])
        self.callback(key)
        self.assertEqual(self.panel.sent[0][-1], 'Woodwork'.encode().hex() + ':0')

    def test_foreign_dead_character_cannot_be_transfer_source(self):
        source = copy.deepcopy(self.panel.state.chars[1]);source.id=2;source.user='Other';source.died_real=10
        self.panel.state.chars[2]=source
        with self.assertRaises(ApiError):
            self.confirm_button('transfer', '2')

    def test_myid_works_before_allowlist_setup_without_panel_access(self):
        self.config.admins.clear()
        self.bot.update({'message': {'from': {'id': 123}, 'chat': {'id': 123, 'type': 'private'}, 'text': '/myid'}})
        self.assertIn('123', self.tg.sent[-1][1])
        self.assertEqual(self.panel.reads, 0)

    def test_expired_buttons_and_new_bot_instance_cannot_replay(self):
        store=Buttons(clock=lambda: 10)
        k=store.add(123,'X','confirm')['callback_data']
        store.clock=lambda: 1000
        self.assertIsNone(store.get(123,k))
        self.assertIsNone(Buttons().get(123,k))

    def test_russian_duration(self):
        self.assertEqual(duration(12619000), '3 часа, 30 минут, 19 секунд')


class TransportTests(unittest.TestCase):
    def test_partial_snapshot_fails_checksum(self):
        msg=frame([['LPRS1','boot',1,2,'1.4.0',180,1,'2026-09-28']])
        with self.assertRaises(ProtocolError):
            rows(msg[:-4])

    def test_snapshot_decodes_cyrillic_without_markup_evaluation(self):
        h=lambda s: s.encode().hex()
        data=frame([['LPRS1','boot',1,2,'1.4.0',180,1,'2026-09-28'],
            ['C',1,h('Игрок'),h('Имя <&>'),0,0,-1,-1,-1,-1,20,10,'sid'],
            ['E',1,1,12,100000,'ready',h('Hand_L'),1],
            ['K',1,h('Woodwork'),h('Строительство'),3,940.25]])
        c=snapshot(data).chars[1]
        self.assertEqual(c.user,'Игрок');self.assertEqual(c.name,'Имя <&>')
        self.assertEqual(c.skills['Woodwork'].xp,940.25)

    def test_panel_write_timeout_does_not_resend_mutation(self):
        config=Config('unused',{123},'https://example.test','12345678','private')
        panel=Panel(config);state=FakePanel().state;calls=[]
        def fake(suffix, content=None):
            calls.append(suffix)
            if suffix=='request':
                req=rows(content)[0];fake.rid=req[1];raise ApiError('timeout')
            return frame([['LPRR1',fake.rid,'boot',1,'ok','wound_applied']])
        panel.call_file=fake
        with patch('transport.time.sleep'):
            result=panel.execute(123,state,state.chars[1],'bite','Head')
        self.assertEqual(result[0],'ok');self.assertEqual(calls.count('request'),1)

    def test_corrupt_snapshot_slot_uses_other_complete_slot(self):
        panel=Panel(Config('unused',set(),'https://example.test','12345678','private'))
        data=frame([['LPRS1','boot',1,2,'1.4.0',180,1,'2026-09-28']])
        panel.call_file=lambda slot: data[:-5] if slot.endswith('a') else data
        self.assertEqual(panel.snapshot().boot,'boot')

    def test_https_and_redirect_policy_prevent_bearer_forwarding(self):
        config=Config('unused',set(),'http://example.test','12345678','private')
        with self.assertRaises(ApiError): config.validate_panel()
        self.assertIsNone(NoRedirect().redirect_request(None,None,302,'',{},'https://elsewhere.test'))


if __name__ == '__main__': unittest.main()
