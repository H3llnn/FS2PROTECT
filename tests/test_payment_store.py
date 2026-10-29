import tempfile
import unittest
from pathlib import Path
from cryptography.fernet import Fernet
from subgate.store import Store
from subgate.payment_store import PaymentStore

class PaymentStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.key = Fernet.generate_key()
        self.path = Path(self.tmp.name)/'db'
        self.db = Store(self.path, self.key, 1)
        self.db.grant(1, 2, 'both')
        self.db.deploy(2, 99, 'PayBot', 1, 'hash', 'token', 'session', kind='payment')
        self.p = PaymentStore(self.db)
        self.p.account(2, 'example', 'recipient', 'secret-key', True)
        self.pkg = self.p.save_package(99, 2, name='VIP', description='Hello', price=1000, target=-1001)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def order(self, user=3):
        return self.p.new_order(99, user, self.pkg)

    def test_types_and_old_grants(self):
        self.db.grant(1, 4)
        self.assertTrue(self.db.allowed(4, 'forcesubs'))
        self.assertFalse(self.db.allowed(4, 'payment'))
        self.db.grant(1, 4, 'payment')
        self.assertFalse(self.db.allowed(4, 'forcesubs'))
        self.assertTrue(self.db.allowed(4, 'payment'))

    def test_snapshot_history_and_cancel_disabled(self):
        o = self.order()
        self.p.attach(o['id'], 'tx1', '000201', 1000)
        self.p.save_package(99, 2, self.pkg, name='New', description='X', price=2000, target=-1002)
        self.assertEqual(self.p.order(99, o['id'])['price'], 1000)
        self.p.package_status(99, 2, self.pkg, 'inactive')
        self.assertEqual(self.p.order(99, o['id'])['state'], 'cancelled')
        self.assertEqual(self.p.accept(2, 'tx1', 1000), 'late')
        self.assertEqual(self.p.history(99, 3), [])

    def test_duplicate_and_mismatch(self):
        o = self.order()
        self.p.attach(o['id'], 'tx1', '000201', 1000)
        with self.assertRaises(ValueError): self.p.accept(2, 'tx1', 999)
        self.assertEqual(self.p.accept(2, 'tx1', 1000), 'verified')
        self.assertEqual(self.p.accept(2, 'tx1', 1000), 'duplicate')
        self.assertEqual(len(self.p.history(99, 3)), 1)
        self.p.package_status(99, 2, self.pkg, 'deleted')
        self.assertEqual(len(self.p.history(99, 3)), 1)

    def test_owner_user_bot_isolation(self):
        with self.assertRaises(PermissionError): self.p.save_package(99, 3, name='X', price=1, target=-1)
        o = self.order()
        with self.assertRaises(PermissionError): self.p.cancel(99, 4, o['id'])
        with self.assertRaises(ValueError): self.p.order(100, o['id'])
        self.p.attach(o['id'], 'tx1', '000201', 1000)
        self.assertEqual(self.p.accept(7, 'tx1', 1000), 'unmatched')

    def test_account_change_blocked_by_orders(self):
        self.order()
        with self.assertRaises(ValueError): self.p.account(2, 'another', 'other', 'other-key', True)

    def test_restart_and_secrets(self):
        o = self.order()
        self.p.attach(o['id'], 'tx1', '000201', 1000)
        self.assertNotIn('secret-key', str(self.db.rows('SELECT * FROM payment_accounts')))
        self.db.close()
        self.db = Store(self.path, self.key, 1)
        self.p = PaymentStore(self.db)
        self.assertEqual(self.p.order(99, o['id'])['transaction_id'], 'tx1')
        self.assertTrue(self.db.allowed(2, 'payment'))

    def test_typed_revoke(self):
        o = self.order()
        self.db.revoke(1, 2, 'payment')
        self.assertTrue(self.db.allowed(2, 'forcesubs'))
        self.assertFalse(self.db.allowed(2, 'payment'))
        self.assertFalse(self.db.bot(99)['active'])
        self.assertEqual(self.p.order(99, o['id'])['state'], 'cancelled')

    def test_legacy_database_keeps_force_links_and_grants(self):
        import sqlite3
        path=Path(self.tmp.name)/'legacy'
        conn=sqlite3.connect(path)
        conn.executescript("CREATE TABLE creators(id INTEGER PRIMARY KEY,allowed INTEGER NOT NULL); INSERT INTO creators VALUES(7,1); CREATE TABLE bots(id INTEGER PRIMARY KEY,owner INTEGER NOT NULL,username TEXT NOT NULL,credentials BLOB NOT NULL,active INTEGER NOT NULL DEFAULT 1,settings TEXT NOT NULL DEFAULT '{}'); INSERT INTO bots VALUES(77,7,'OldBot',X'00',1,'{}');")
        conn.close()
        legacy=Store(path,self.key,1)
        try:
            self.assertEqual(legacy.bot(77)['kind'],'forcesubs')
            self.assertTrue(legacy.allowed(7,'forcesubs'))
            self.assertFalse(legacy.allowed(7,'payment'))
            key=legacy.link(77,7,[(-1001,4)])
            self.assertEqual(legacy.sources(77,key),[(-1001,4)])
        finally: legacy.close()

    def test_two_bots_share_account_but_not_history(self):
        self.db.deploy(2,100,'OtherBot',1,'h','t','s',kind='payment')
        pkg=self.p.save_package(100,2,name='Other',price=1000,target=-1002)
        first=self.order(); self.p.attach(first['id'],'t1','000201',1000)
        other=self.p.new_order(100,3,pkg); self.p.attach(other['id'],'t2','000201',1000)
        self.p.accept(2,'t1',1000)
        self.assertEqual(len(self.p.history(99,3)),1)
        self.assertEqual(self.p.history(100,3),[])
        with self.assertRaises(ValueError): self.p.order(100,first['id'])
