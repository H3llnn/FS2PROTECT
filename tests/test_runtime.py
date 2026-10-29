import tempfile
import unittest
from pathlib import Path
from cryptography.fernet import Fernet

from subgate.store import Store
from subgate.runtime import Manager
from subgate.ui import ChildUI, MasterUI
from test_service import FakeAPI


class FakeRunner:
    def __init__(self, api):
        self.api = api
        self.stopped = False

    async def stop(self):
        self.stopped = True


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Store(Path(self.tmp.name)/'db', Fernet.generate_key(), 1)
        self.db.grant(1, 2)
        self.api = FakeAPI()
        async def auth(api_id, api_hash, token):
            return {'id': 99, 'username': 'ExampleBot'}, 'session'
        def factory(record, credentials):
            return FakeRunner(self.api)
        self.manager = Manager(self.db, 500, authenticate=auth, runner_factory=factory)

    async def asyncTearDown(self):
        await self.manager.close()
        self.db.close()
        self.tmp.cleanup()

    async def deploy(self):
        return await self.manager.deploy(2, 123, 'a'*32, '99:'+'x'*30)

    async def test_revoke_stops_all_and_regrant_requires_redeploy(self):
        await self.deploy()
        runner = self.manager.running[99]
        await self.manager.revoke(1, 2)
        self.assertTrue(runner.stopped)
        self.assertEqual(self.manager.running, {})
        self.db.grant(1, 2)
        await self.manager.restore()
        self.assertEqual(self.manager.running, {})
        await self.deploy()
        self.assertIn(99, self.manager.running)

    async def test_restore_only_active_authorized_bots(self):
        await self.deploy()
        await self.manager.close()
        await self.manager.restore()
        self.assertIn(99, self.manager.running)
        await self.manager.toggle(1, 99, False)
        await self.manager.restore()
        self.assertNotIn(99, self.manager.running)

    async def test_revoked_bot_requires_redeploy_even_after_regrant(self):
        await self.deploy()
        await self.manager.revoke(1, 2)
        self.db.grant(1, 2)
        with self.assertRaises(PermissionError):
            await self.manager.toggle(1, 99, True)
        await self.deploy()
        self.assertIn(99, self.manager.running)

    async def test_revocation_during_auth_does_not_activate_bot(self):
        import asyncio
        started = asyncio.Event()
        proceed = asyncio.Event()
        async def auth(*args):
            started.set()
            await proceed.wait()
            return {'id': 99, 'username': 'ExampleBot'}, 'session'
        self.manager.authenticate = auth
        task = asyncio.create_task(self.deploy())
        await started.wait()
        await self.manager.revoke(1, 2)
        proceed.set()
        with self.assertRaises(PermissionError):
            await task
        self.assertEqual(self.manager.running, {})

    async def test_unauthorized_deploy_and_token_takeover(self):
        with self.assertRaises(PermissionError):
            await self.manager.deploy(3, 123, 'a'*32, '99:'+'x'*30)
        await self.deploy()
        self.db.grant(1, 3)
        with self.assertRaises(PermissionError):
            await self.manager.deploy(3, 123, 'a'*32, '99:'+'x'*30)
        self.assertEqual(self.db.bot(99)['owner'], 2)

    async def test_child_callback_owner_guard(self):
        await self.deploy()
        ui = ChildUI(self.db, 99, self.api)
        self.db.admin(99, 2, 3, True)
        await ui.handle({'callback_query': {'id': 'a', 'from': {'id': 3},
            'data': 's:protection', 'message': {'chat': {'id': 3}, 'message_id': 1}}})
        self.assertFalse(self.db.settings(99)['protection'])
        await ui.handle({'message': {'from': {'id': 3}, 'chat': {'id': 3, 'type': 'private'},
                                    'message_id': 2, 'text': '/broadcast'}})
        self.assertFalse(any('broadcast' in str(a) for m,a in self.api.calls if m == 'copyMessage'))

    async def test_master_callbacks_cannot_grant_as_creator(self):
        ui = MasterUI(self.db, self.api, self.manager)
        await ui.handle({'callback_query': {'id': 'a', 'from': {'id': 2},
            'data': 'm:grant', 'message': {'chat': {'id': 2}, 'message_id': 1}}})
        self.assertNotIn(2, ui.pending)

    async def test_enrollment_requires_credentials_every_time(self):
        ui = MasterUI(self.db, self.api, self.manager)
        async def send(text):
            await ui.handle({'message': {'from': {'id': 2}, 'chat': {'id': 2, 'type': 'private'},
                                         'message_id': 1, 'text': text}})
        await send('/buatbot')
        self.assertEqual(ui.pending[2]['step'], 'api_id')
        await send('123')
        self.assertEqual(ui.pending[2]['step'], 'api_hash')
        await send('a'*32)
        await send('99:'+'x'*30)
        self.assertNotIn(2, ui.pending)
        await send('/buatbot')
        self.assertEqual(ui.pending[2]['step'], 'api_id')

    async def test_payment_permission_and_kind_are_enforced(self):
        with self.assertRaises(PermissionError):
            await self.manager.deploy(2,123,'a'*32,'99:'+'x'*30,kind='payment')
        self.db.grant(1,2,'both')
        await self.manager.deploy(2,123,'a'*32,'99:'+'x'*30,kind='payment')
        self.assertEqual(self.db.bot(99)['kind'],'payment')
        with self.assertRaises(ValueError):
            await self.manager.deploy(2,123,'a'*32,'99:'+'x'*30,kind='forcesubs')
        self.assertIn(99,self.manager.running)
        await self.manager.grant(1,2,'forcesubs')
        self.assertNotIn(99,self.manager.running)
        self.assertFalse(self.db.bot(99)['active'])
        self.assertTrue(self.db.allowed(2,'forcesubs'))
