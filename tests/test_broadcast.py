import asyncio
import time
import unittest
from subgate.broadcast import Broadcast


class DB:
    def users(self, bot):
        assert bot == 99
        return [10, 11, 12]


class API:
    def __init__(self):
        self.calls = []
        self.after_copy = None
        self.fail = set()

    async def call(self, method, **args):
        self.calls.append((method, args))
        if method == 'copyMessage' and args['chat_id'] in self.fail:
            raise RuntimeError('blocked')
        if method == 'copyMessage' and self.after_copy:
            self.after_copy(args)
        return {'message_id': len(self.calls)}


class BroadcastTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.api = API()
        self.allowed = {1, 2}
        self.broadcast = Broadcast(DB(), 99, self.api, self.allowed.__contains__, interval=0)

    async def asyncTearDown(self):
        await self.broadcast.close()

    async def test_preview_scope_failure_and_durable_report(self):
        shown = []
        async def show(*args):
            shown.append(args)
        self.broadcast.show = show
        nonce = await self.broadcast.preview(1, 45)
        self.assertEqual(self.api.calls, [('copyMessage', dict(chat_id=1, from_chat_id=1, message_id=45))])
        self.assertEqual(shown[0][2][0][0]['callback_data'], f'bc:send:{nonce}')
        self.api.fail.add(11)
        await (await self.broadcast.start(1, nonce))
        copied = [a['chat_id'] for m, a in self.api.calls if m == 'copyMessage']
        self.assertEqual(copied, [1, 10, 11, 12])
        self.assertEqual(next((m,a) for m,a in reversed(self.api.calls) if m=='sendMessage'), ('sendMessage', dict(chat_id=1, text='✅ Broadcast selesai\n\n📨 Terkirim: 2\n⚠️ Gagal: 1')))
        self.assertTrue(all(m != 'deleteMessage' for m, _ in self.api.calls))

    async def test_unauthorized_actor_replay_cancel_and_expiry(self):
        with self.assertRaises(PermissionError):
            await self.broadcast.preview(3, 45)
        nonce = await self.broadcast.preview(1, 45)
        with self.assertRaises(ValueError):
            await self.broadcast.start(2, nonce)
        self.allowed.remove(1)
        with self.assertRaises(PermissionError):
            await self.broadcast.start(1, nonce)
        self.allowed.add(1)
        self.broadcast.cancel(1)
        with self.assertRaises(ValueError):
            await self.broadcast.start(1, nonce)
        nonce = await self.broadcast.preview(1, 45)
        self.broadcast.previews[1]['expires'] = time.monotonic() - 1
        with self.assertRaises(ValueError):
            await self.broadcast.start(1, nonce)
        nonce = await self.broadcast.preview(1, 45)
        task = await self.broadcast.start(1, nonce)
        with self.assertRaises(ValueError):
            await self.broadcast.start(1, nonce)
        await task
        with self.assertRaises(ValueError):
            await self.broadcast.start(1, nonce)

    async def test_stop_creator_only_and_counts(self):
        nonce = await self.broadcast.preview(2, 45)
        entered, release = asyncio.Event(), asyncio.Event()
        async def show(*args):
            entered.set()
            await release.wait()
        self.broadcast.show = show
        task = await self.broadcast.start(2, nonce)
        await entered.wait()
        self.assertFalse(await self.broadcast.stop(1, nonce))
        self.assertFalse(await self.broadcast.stop(2, 'wrong'))
        self.assertTrue(await self.broadcast.stop(2, nonce))
        release.set()
        await task
        self.assertEqual(next((m,a) for m,a in reversed(self.api.calls) if m=='sendMessage')[1]['text'], '⏹ Broadcast dihentikan\n\n📨 Terkirim: 0\n⚠️ Gagal: 0\n⏳ Belum dikirim: 3')

    async def test_revocation_stops_future_sends(self):
        nonce = await self.broadcast.preview(1, 45)
        def revoke(args):
            self.allowed.remove(1)
        self.api.after_copy = revoke
        await (await self.broadcast.start(1, nonce))
        self.assertEqual(next((m,a) for m,a in reversed(self.api.calls) if m=='sendMessage')[1]['text'], '⏹ Broadcast dihentikan\n\n📨 Terkirim: 1\n⚠️ Gagal: 0\n⏳ Belum dikirim: 2')

    async def test_close_cancels_job_and_reports(self):
        nonce = await self.broadcast.preview(1, 45)
        entered = asyncio.Event()
        async def show(*args):
            entered.set()
            await asyncio.Event().wait()
        self.broadcast.show = show
        await self.broadcast.start(1, nonce)
        await entered.wait()
        await self.broadcast.close()
        self.assertFalse(self.broadcast.jobs)
        self.assertIn('⏳ Belum dikirim: 3', next((m,a) for m,a in reversed(self.api.calls) if m=='sendMessage')[1]['text'])
