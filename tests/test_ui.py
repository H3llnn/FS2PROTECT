import tempfile
import unittest
from pathlib import Path
from cryptography.fernet import Fernet

from subgate.store import Store, DEFAULTS
from subgate.copy import DENIED_UPLOAD
from subgate.ui import ChildUI
from test_service import FakeAPI


class UITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Store(Path(self.tmp.name)/'db', Fernet.generate_key(), 1)
        self.db.grant(1, 2)
        self.db.deploy(2, 99, 'ExampleBot', 1, 'hash', 'token', 'session')
        self.api = FakeAPI()
        self.ui = ChildUI(self.db, 99, self.api)

    async def asyncTearDown(self):
        self.db.close()
        self.tmp.cleanup()

    async def send(self, user=2, **message):
        await self.ui.handle({'message': {'from': {'id': user}, 'chat': {'id': user, 'type': 'private'},
                                         'message_id': 7, **message}})

    async def test_unauthorized_file_denial(self):
        await self.send(3, document={'file_id': 'x'})
        self.assertEqual(self.api.calls[-1][1]['text'], DENIED_UPLOAD)

    async def test_photo_and_custom_text_saved_by_owner(self):
        self.ui.wait(2, 'setting', key='welcome_photo')
        await self.send(photo=[{'file_id': 'photo1'}])
        self.assertEqual(self.db.settings(99)['welcome_photo']['file_id'], 'photo1')
        await self.send(3, text='/start')
        self.assertEqual(self.api.calls[-1][0], 'sendPhoto')

    async def test_invalid_notice_template_not_saved(self):
        self.ui.wait(2, 'setting', key='delete_notice')
        await self.send(text='{durasi.__class__}')
        self.assertEqual(self.db.settings(99)['delete_notice'], DEFAULTS['delete_notice'])

    async def test_batch_retains_caption_implicitly_via_copy_and_order(self):
        self.db.setting(99, 2, 'database', -100123)
        async def valid(*args, **kwargs):
            return {}
        self.ui.delivery.validate_chat = valid
        await self.send(text='/batch')
        await self.send(document={'file_id': 'a'}, caption='Original caption')
        await self.send(document={'file_id': 'b'}, caption='Another caption')
        self.assertEqual(len(self.ui.pending[2]['sources']), 2)
        await self.ui.callback(2, 'b:done', {})
        link = self.api.calls[-1][1]['text'].split('start=')[1]
        self.assertEqual(self.db.sources(99, link), [(-100123, 102), (-100123, 104)])
        copies = [a for m,a in self.api.calls if m == 'copyMessage']
        self.assertTrue(all('caption' not in a for a in copies))

    async def test_admin_removed_during_batch_cannot_finish(self):
        self.db.admin(99, 2, 3, True)
        self.ui.wait(3, 'batch', sources=[(-100123, 1)])
        self.db.admin(99, 2, 3, False)
        with self.assertRaises(PermissionError):
            await self.ui.finish_batch(3)
