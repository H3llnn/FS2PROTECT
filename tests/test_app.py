import unittest
from cryptography.fernet import Fernet
from subgate.app import Config


class ConfigTests(unittest.TestCase):
    def test_requires_valid_owner_token_and_encryption_key(self):
        valid = {'MASTER_OWNER_ID': '1', 'MASTER_BOT_TOKEN': '123:'+'x'*30,
                 'SECRET_KEY': Fernet.generate_key().decode(), 'DATA_DIR': './data'}
        self.assertEqual(Config.read(valid).owner, 1)
        for name, value in [('MASTER_OWNER_ID', '0'), ('MASTER_BOT_TOKEN', 'bad'), ('SECRET_KEY', '')]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                Config.read(valid | {name: value})
