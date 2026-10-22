import tempfile
import unittest
from pathlib import Path
from cryptography.fernet import Fernet

from subgate.store import Store
from subgate.service import Delivery, TelegramFailure


class FakeAPI:
    def __init__(self):
        self.calls = []
        self.counter = 100
        self.members = {}
        self.fail_copy = None
        self.delete_error = False

    async def call(self, method, **args):
        self.calls.append((method, args))
        if method == 'getChatMember':
            status = self.members.get((args['chat_id'], args['user_id']),
                                      'administrator' if args['user_id'] == 99 else 'member')
            if isinstance(status, Exception):
                raise status
            return {'status': status}
        if method == 'copyMessage' and args['message_id'] == self.fail_copy:
            raise TelegramFailure(400, 'copy failed')
        if method == 'deleteMessage' and self.delete_error:
            raise TelegramFailure(500, 'temporary')
        if method in ('copyMessage', 'sendMessage', 'sendPhoto'):
            self.counter += 1
            return {'message_id': self.counter}
        return True


class DeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Store(Path(self.tmp.name) / 'db', Fernet.generate_key(), 1)
        self.db.grant(1, 2)
        self.db.deploy(2, 99, 'ExampleBot', 1, 'hash', 'token', 'session')
        self.api = FakeAPI()
        self.service = Delivery(self.db, 99, self.api, clock=lambda: 1000)
        self.key = self.db.link(99, 2, [(-100123, 7), (-100123, 8)])

    async def asyncTearDown(self):
        self.db.close()
        self.tmp.cleanup()

    async def test_only_missing_join_targets_and_retry_token(self):
        self.db.target(99, 2, -1001, 'channel', 'https://t.me/a')
        self.db.target(99, 2, -1002, 'group', 'https://t.me/b')
        self.api.members[(-1002, 3)] = 'left'
        self.assertFalse(await self.service.deliver(3, self.key))
        joins = self.api.calls[-1][1]['reply_markup']['inline_keyboard']
        self.assertEqual(joins[0], [{'text': 'Join Group', 'url': 'https://t.me/b'}])
        self.assertEqual(joins[-1][0]['text'], 'Coba Lagi')
        self.assertIn(self.key, joins[-1][0]['callback_data'])
        self.assertFalse(any(m == 'copyMessage' for m, a in self.api.calls))

    async def test_admin_bypass_order_and_notice_jobs(self):
        self.db.admin(99, 2, 3, True)
        self.db.target(99, 2, -1001, 'channel', 'https://t.me/a')
        self.assertTrue(await self.service.deliver(3, self.key))
        copied = [a for m, a in self.api.calls if m == 'copyMessage']
        self.assertEqual([a['message_id'] for a in copied], [7, 8])
        self.assertFalse(copied[0]['protect_content'])
        self.assertFalse(any(m == 'getChatMember' and a['user_id'] == 3 for m, a in self.api.calls))
        jobs = self.db.due(2801)
        self.assertEqual(len(jobs), 3)
        self.assertEqual(jobs[0]['due'], 2800)
        self.assertIn('30 menit', self.api.calls[-1][1]['text'])

    async def test_membership_error_fails_closed_deduplicates_and_recovers(self):
        self.db.target(99, 2, -1001, 'channel', 'https://t.me/a')
        self.api.members[(-1001, 3)] = TelegramFailure(403, 'no access')
        await self.service.deliver(3, self.key)
        await self.service.deliver(3, self.key)
        owner_notices = [a for m,a in self.api.calls if m == 'sendMessage' and a['chat_id'] == 2]
        self.assertEqual(len(owner_notices), 1)
        self.assertFalse(any(m == 'copyMessage' for m,a in self.api.calls))
        self.api.members[(-1001, 3)] = 'member'
        await self.service.deliver(3, self.key)
        owner_notices = [a for m,a in self.api.calls if m == 'sendMessage' and a['chat_id'] == 2]
        self.assertEqual(len(owner_notices), 2)

    async def test_partial_delivery_schedules_already_sent_file(self):
        self.api.fail_copy = 8
        self.assertFalse(await self.service.deliver(3, self.key))
        self.assertGreaterEqual(len(self.db.due(2801)), 1)
        self.assertEqual(self.db.due(2801)[0]['message_id'], 101)

    async def test_deletion_disabled(self):
        self.db.setting(99, 2, 'delete_seconds', 0)
        await self.service.deliver(3, self.key)
        self.assertEqual(self.db.due(99999), [])
        self.assertEqual(len([m for m,a in self.api.calls if m == 'copyMessage']), 2)
        self.assertFalse(any(m == 'sendMessage' for m,a in self.api.calls))

    async def test_deletion_retries_and_never_deletes_source(self):
        await self.service.deliver(3, self.key)
        self.api.delete_error = True
        await self.service.expire(2801)
        self.assertEqual(len(self.db.due(2862)), 3)
        self.api.delete_error = False
        await self.service.expire(2862)
        self.assertEqual(self.db.due(99999), [])
        self.assertTrue(all(a['chat_id'] == 3 for m,a in self.api.calls if m == 'deleteMessage'))

    async def test_unknown_link_and_cross_bot_never_release(self):
        self.assertFalse(await self.service.deliver(3, 'does-not-exist'))
        self.assertFalse(any(m == 'copyMessage' for m,a in self.api.calls))

    async def test_copy_failure_is_not_misreported_as_chat_recovery(self):
        self.api.fail_copy = 8
        await self.service.deliver(3, self.key)
        self.assertEqual([r['scope'] for r in self.db.incidents()], ['file:-100123:8'])
        self.api.fail_copy = None
        await self.service.deliver(3, self.key)
        self.assertEqual(self.db.incidents(), [])

    async def test_self_admin_failure_never_releases_file(self):
        self.db.target(99, 2, -1001, 'channel', 'https://t.me/a')
        self.api.members[(-1001, 99)] = 'member'
        self.assertFalse(await self.service.deliver(3, self.key))
        self.assertFalse(any(m == 'copyMessage' for m,a in self.api.calls))
