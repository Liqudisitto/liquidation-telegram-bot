import io
import json
import unittest
import urllib.error
from unittest.mock import patch
import test_bot as base
from test_bot import FakeTelegram
from bot import UIError
from transport import ApiError, Telegram, TelegramError
from ui import LIMBS, restore_parts


class MenuTests(unittest.TestCase):
    setUp = base.BotTests.setUp
    callback = base.BotTests.callback
    confirm_button = base.BotTests.confirm_button

    def test_all_navigation_and_commands_edit_one_message(self):
        self.bot.command(123, '/start')
        mid = self.bot.messages[123]
        self.bot.route(123, 'users', {'online': True})
        self.bot.route(123, 'user', {'user': 'User'})
        self.bot.route(123, 'character', {'cid': 1})
        self.bot.route(123, 'skills', {'cid': 1})
        self.bot.route(123, 'level', {'cid': 1, 'perk': 'Woodwork'})
        self.bot.command(123, '/todaytime User')
        self.assertEqual(self.tg.sent, [mid])
        self.assertEqual(len([c for c in self.tg.calls if c[0] == 'editMessageText']), 6)

    def test_every_action_returns_to_same_character_with_receipt(self):
        c = self.panel.state.chars[1]
        for action, arg in [('scratch','Head'), ('cut','Hand_R'), ('bite','Head'),
                            ('amputate','Hand_R'), ('restore','Hand_L'),
                            ('setskill','Woodwork:5'), ('heal','-'), ('kill','-')]:
            with self.subTest(action=action):
                c.toc, c.amputated = 'ready', {'Hand_L'}
                key = self.confirm_button(action, arg)
                self.callback(key)
                text, keys = self.tg.history[-1][1:]
                self.assertIn(c.name, text)
                self.assertIn('Запрос: abc', text)
                captions = [b['text'] for row in keys for b in row]
                self.assertIn('📚 Навыки', captions)
                self.assertIn('К игроку', captions)
                self.assertNotIn('🟢 Онлайн', captions)
                self.assertEqual(len(self.tg.sent), 1)
        self.assertEqual(len(self.panel.sent), 8)

    def test_restore_only_offers_highest_missing_segment_per_side(self):
        c = self.panel.state.chars[1]
        c.toc, c.amputated = 'ready', set(LIMBS)
        self.assertEqual(restore_parts(c), ['UpperArm_L', 'UpperArm_R'])
        self.bot.route(123, 'parts', {'cid':1, 'action':'restore'})
        keys = self.tg.history[-1][2]
        choices = [self.bot.buttons.values[b['callback_data']]['data']
                   for row in keys for b in row]
        self.assertEqual([d['arg'] for d in choices if 'arg' in d], ['UpperArm_L','UpperArm_R'])
        with self.assertRaises(ApiError):
            self.confirm_button('restore', 'Hand_L')

    def test_action_result_survives_failed_card_refresh_without_resend(self):
        key = self.confirm_button('scratch', 'Head')
        reads = self.panel.reads
        original = self.panel.snapshot
        def read():
            if self.panel.reads > reads:
                raise ApiError('offline')
            return original()
        self.panel.snapshot = read
        self.callback(key)
        self.assertIn('Запрос: abc', self.tg.history[-1][1])
        self.assertIn('пока не обновилась', self.tg.history[-1][1])
        self.assertEqual(len(self.panel.sent), 1)
        self.assertEqual(len(self.tg.sent), 1)
        captions = [b['text'] for row in self.tg.history[-1][2] for b in row]
        self.assertIn('↻ Обновить', captions)
        self.assertNotIn('💀 Убить', captions)

    def test_deleted_message_is_the_only_edit_failure_that_sends_replacement(self):
        self.bot.command(123, '/start')
        with patch.object(self.tg, 'edit', side_effect=TelegramError('not_editable')):
            self.bot.command(123, '/menu')
        self.assertEqual(len(self.tg.sent), 2)
        for error in (ApiError('timeout'), TelegramError('failed')):
            with patch.object(self.tg, 'edit', side_effect=error):
                with self.assertRaises(UIError):
                    self.bot.command(123, '/menu')
        self.assertEqual(len(self.tg.sent), 2)

    def test_result_edit_timeout_keeps_receipt_and_cannot_repeat_action(self):
        key = self.confirm_button('scratch', 'Head')
        original = self.tg.edit
        def edit(*args):
            if self.panel.sent:
                raise ApiError('timeout')
            return original(*args)
        with patch.object(self.tg, 'edit', side_effect=edit):
            with self.assertRaises(UIError):
                self.callback(key)
        self.assertEqual(len(self.panel.sent), 1)
        self.assertIn('Запрос: abc', self.bot.results[123][1])
        self.bot.route(123, 'character', {'cid':1})
        self.assertIn('Запрос: abc', self.tg.history[-1][1])
        self.callback(key)
        self.assertEqual(len(self.panel.sent), 1)
        self.assertEqual(len(self.tg.sent), 1)

    def test_long_unicode_report_paginates_without_extra_messages(self):
        text = '🧟' * 4000 + 'конец'
        self.bot.show(123, text)
        self.assertLessEqual(len(self.tg.history[-1][1].encode('utf-16-le'))//2, 4096)
        key = self.tg.history[-1][2][0][-1]['callback_data']
        self.callback(key)
        self.assertIn('Страница 2/3', self.tg.history[-1][1])
        key = self.tg.history[-1][2][0][-1]['callback_data']
        self.callback(key)
        self.assertIn('конец', self.tg.history[-1][1])
        self.assertEqual(len(self.tg.sent), 1)
        self.assertEqual(self.panel.reads, 0)

    def test_cancel_or_navigate_invalidates_old_confirmation(self):
        key = self.confirm_button()
        self.bot.route(123, 'character', {'cid':1})
        self.callback(key)
        self.assertEqual(self.panel.sent, [])

    def test_different_admins_have_separate_message_ids(self):
        self.config.admins.add(456)
        self.bot.command(123, '/start')
        self.bot.command(456, '/start')
        self.bot.command(123, '/menu')
        self.assertNotEqual(self.bot.messages[123], self.bot.messages[456])
        self.assertEqual(len(self.tg.sent), 2)
        self.assertEqual(self.tg.calls[-1][1]['message_id'], self.bot.messages[123])


class TelegramEditTests(unittest.TestCase):
    def test_http_400_description_is_classified_without_exposing_token(self):
        for description, reason in [('Bad Request: message is not modified','not_modified'),
            ('Bad Request: message to edit not found','not_editable'),
            ("Bad Request: message can't be edited",'not_editable'),
            ('Bad Request: other secret','failed')]:
            error = urllib.error.HTTPError('https://api.telegram.org/botSECRET/',400,'bad',{},
                io.BytesIO(json.dumps({'ok':False,'error_code':400,'description':description}).encode()))
            with patch('transport.urllib.request.build_opener') as opener:
                opener.return_value.open.side_effect = error
                tg = Telegram('SECRET')
                if reason == 'not_modified':
                    self.assertEqual(tg.edit(123,42,'same')['message_id'],42)
                else:
                    with self.assertRaises(TelegramError) as raised:
                        tg.edit(123,42,'same')
                    self.assertEqual(raised.exception.reason,reason)
                    self.assertNotIn('SECRET',str(raised.exception))
                    self.assertNotIn('secret',str(raised.exception))

    def test_edit_removes_old_keyboard_and_uses_plain_text(self):
        tg = FakeTelegram()
        tg.edit(123,42,'<Игрок>')
        method, data = tg.calls[-1]
        self.assertEqual(method,'editMessageText')
        self.assertEqual(data['reply_markup'],{'inline_keyboard':[]})
        self.assertNotIn('parse_mode',data)
