import tempfile
import unittest
from pathlib import Path

from cryptography.fernet import Fernet
from subgate.store import Store


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'db.sqlite'
        self.key = Fernet.generate_key()
        self.db = Store(self.path, self.key, 1)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def deploy(self, owner=2, bot=99):
        self.db.grant(1, owner)
        self.db.deploy(owner, bot, 'ExampleBot', 1234, 'a' * 32, '99:secret', 'session')

    def test_only_master_grants_and_revokes(self):
        with self.assertRaises(PermissionError):
            self.db.grant(2, 3)
        self.deploy()
        self.db.revoke(1, 2)
        self.assertFalse(self.db.allowed(2))
        self.assertFalse(self.db.bot(99)['active'])
        self.db.grant(1, 2)
        self.assertFalse(self.db.bot(99)['active'])
        self.deploy()
        self.assertTrue(self.db.bot(99)['active'])

    def test_ownership_survives_token_rotation(self):
        self.deploy()
        self.db.grant(1, 3)
        with self.assertRaises(PermissionError):
            self.db.deploy(3, 99, 'ExampleBot', 1, 'hash', 'new', 'session')
        self.db.deploy(2, 99, 'ExampleBot', 1, 'hash', 'new', 'new-session')
        self.assertEqual(self.db.credentials(99)['token'], 'new')

    def test_child_settings_and_limits_are_isolated(self):
        self.deploy()
        self.deploy(bot=100)
        with self.assertRaises(PermissionError):
            self.db.setting(99, 3, 'database', -100123)
        self.db.admin(99, 2, 3, True)
        self.assertTrue(self.db.can_upload(99, 3))
        with self.assertRaises(PermissionError):
            self.db.setting(99, 3, 'protection', True)
        self.assertFalse(self.db.settings(99)['protection'])
        self.assertEqual(self.db.settings(99)['delete_seconds'], 1800)
        for i in range(4):
            self.db.target(99, 2, -1000-i, 'channel', 'https://t.me/test')
        with self.assertRaises(ValueError):
            self.db.target(99, 2, -2000, 'group', 'https://t.me/test')
        self.assertEqual(self.db.targets(100), [])
        with self.assertRaises(ValueError):
            self.db.setting(99, 2, 'delete_seconds', -1)

    def test_links_retain_order_source_and_survive_redeploy(self):
        self.deploy()
        self.db.setting(99, 2, 'database', -100123)
        key = self.db.link(99, 2, [(-100123, 7), (-100123, 2)])
        self.db.setting(99, 2, 'database', -100456)
        self.db.revoke(1, 2)
        self.deploy()
        self.assertEqual(self.db.sources(99, key), [(-100123, 7), (-100123, 2)])
        self.assertEqual(self.db.sources(100, key), [])

    def test_credentials_are_encrypted_at_rest(self):
        self.deploy()
        self.db.conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        raw = self.path.read_bytes()
        self.assertNotIn(b'99:secret', raw)
        self.assertNotIn(b'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', raw)
        self.assertEqual(self.db.credentials(99)['api_id'], 1234)

    def test_jobs_and_incidents_survive_restart(self):
        self.deploy()
        self.db.schedule(99, 44, 5, 100)
        self.assertEqual(self.db.due(101)[0]['message_id'], 5)
        self.assertTrue(self.db.incident(99, 'chat:-100', True))
        self.assertFalse(self.db.incident(99, 'chat:-100', True))
        self.db.close()
        self.db = Store(self.path, self.key, 1)
        self.assertEqual(len(self.db.due(101)), 1)
        self.assertTrue(self.db.incident(99, 'chat:-100', False))
        self.assertFalse(self.db.incident(99, 'chat:-100', False))
        self.db.finish_job(self.db.due(101)[0]['id'])
        self.assertEqual(self.db.due(101), [])
