import sqlite3
import unittest
from types import SimpleNamespace

from subgate.ui_base import BaseUI
from subgate.service import TelegramFailure
from test_service import FakeAPI


class DisplayTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.db = SimpleNamespace(conn=self.conn)
        self.api = FakeAPI()
        self.ui = BaseUI(self.db, self.api)

    async def asyncTearDown(self):
        await self.ui.close()
        self.conn.close()

    def deleted(self):
        return [args['message_id'] for method, args in self.api.calls if method == 'deleteMessage']

    async def test_replaces_only_screen_after_successful_send(self):
        first = await self.ui.text(2, 'menu')
        durable = await self.ui.durable(2, 'access link')
        photo = await self.api.call('sendPhoto', chat_id=2, photo='delivered-content')
        await self.ui.text(2, 'settings')
        self.assertEqual(self.deleted(), [first['message_id']])
        self.assertNotIn(durable['message_id'], self.deleted())
        self.assertNotIn(photo['message_id'], self.deleted())
        self.assertEqual([m for m, _ in self.api.calls][-2:], ['sendMessage', 'deleteMessage'])

    async def test_grouped_photo_and_text_replaced_together(self):
        await self.ui.photo_text(2, 'welcome', 'x' * 1025)
        ids = [args[0] for args in self.conn.execute('SELECT message_id FROM display_screens')]
        self.assertEqual(len(ids), 2)
        await self.ui.text(2, 'next')
        self.assertCountEqual(self.deleted(), ids)

    async def test_short_photo_is_one_screen(self):
        await self.ui.photo_text(2, 'welcome', 'caption')
        self.assertEqual(self.api.calls[-1][1]['caption'], 'caption')
        await self.ui.text(2, 'next')
        self.assertEqual(len(self.deleted()), 1)

    async def test_failed_delete_removes_keyboard(self):
        await self.ui.text(2, 'old')
        self.api.delete_error = True
        await self.ui.text(2, 'new')
        self.assertEqual(self.api.calls[-1][0], 'editMessageReplyMarkup')
        self.assertEqual(self.api.calls[-1][1]['reply_markup'], {'inline_keyboard': []})

    async def test_tracking_survives_ui_recreation_and_is_scoped(self):
        old = await self.ui.text(2, 'old')
        child = BaseUI(self.db, self.api)
        child.bot = 99
        await child.text(2, 'child')
        await self.ui.text(3, 'other user')
        recreated = BaseUI(self.db, self.api)
        await recreated.text(2, 'new')
        self.assertEqual(self.deleted(), [old['message_id']])

    async def test_failed_send_preserves_previous_screen(self):
        first = await self.ui.text(2, 'old')
        original = self.api.call
        async def fail(method, **args):
            if method == 'sendMessage':
                raise TelegramFailure(500, 'failed')
            return await original(method, **args)
        self.api.call = fail
        with self.assertRaises(TelegramFailure):
            await self.ui.text(2, 'new')
        self.assertEqual(self.deleted(), [])
        self.assertEqual(self.conn.execute('SELECT message_id FROM display_screens').fetchone()[0],
                         first['message_id'])
