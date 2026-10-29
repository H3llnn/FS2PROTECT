import tempfile
import unittest
from pathlib import Path
from cryptography.fernet import Fernet
from subgate.store import Store
from subgate.ui import ChildUI, MasterUI
from subgate.runtime import Manager
from test_service import FakeAPI


class UpdateAPI(FakeAPI):
    async def call(self, method, **args):
        if method == 'getChat':
            self.calls.append((method, args))
            return {'id': args['chat_id'], 'type': 'channel', 'title': 'Cinema', 'username': 'Cinema'}
        if method == 'sendMediaGroup':
            self.calls.append((method, args))
            result = []
            for media in args['media']:
                self.counter += 1
                result.append({'message_id': self.counter})
            return result
        if method == 'getMe':
            return {'id': 99, 'username': 'ExampleBot', 'first_name': 'Cinema Room'}
        result = await super().call(method, **args)
        if method == 'getChatMember' and args['user_id'] == 99:
            result.update(can_post_messages=True, can_delete_messages=True, can_invite_users=True)
        return result


class UpdateTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)/'db'
        self.key = Fernet.generate_key()
        self.db = Store(self.path, self.key, 1)
        self.db.grant(1, 2)
        self.db.deploy(2, 99, 'ExampleBot', 1, 'hash', 'token', 'session')
        self.db.setting(99, 2, 'database', -100123)
        self.api = UpdateAPI()
        self.ui = ChildUI(self.db, 99, self.api)
        self.manager = Manager(self.db, 500, authenticate=lambda *a: None, runner_factory=lambda *a: None)
        self.master = MasterUI(self.db, self.api, self.manager)

    async def asyncTearDown(self):
        for ui in (self.ui, self.master):
            if hasattr(ui, 'close'):
                await ui.close()
        self.db.close()
        self.tmp.cleanup()

    async def send(self, text=None, user=2, **extra):
        message = {'chat': {'id': user, 'type': 'private'}, 'from': {'id': user, 'first_name': '<Zeisss>'},
                   'message_id': 7, **extra}
        if text is not None:
            message['text'] = text
        await self.ui.handle({'message': message})

    async def test_text_link_for_owner_admin_and_denied_ordinary_user(self):
        self.db.admin(99, 2, 3, True)
        for user in (2, 3):
            await self.send('A text\nSecond line', user=user)
            button = self.api.calls[-1][1]['reply_markup']['inline_keyboard'][0][0]
            link = button['copy_text']['text']
            self.assertEqual(len(self.db.sources(99, link.split('start=')[1])), 1)
        before = len([m for m,a in self.api.calls if m == 'copyMessage'])
        await self.send('No access', user=4)
        self.assertEqual(len([m for m,a in self.api.calls if m == 'copyMessage']), before)
        self.assertIn('Akses terbatas', next(args['text'] for method,args in reversed(self.api.calls) if method=='sendMessage'))

    async def test_batch_album_splits_at_text_document_and_preserves_captions(self):
        await self.send('/batch')
        await self.send(photo=[{'file_id': 'p1'}], caption='Photo caption')
        await self.send(video={'file_id': 'v1'}, caption='Video caption')
        await self.send('Middle text')
        await self.send(document={'file_id': 'doc'})
        await self.send(photo=[{'file_id': 'p2'}])
        await self.send(photo=[{'file_id': 'p3'}])
        await self.ui.callback(2, 'b:done', {})
        link = self.api.calls[-1][1]['reply_markup']['inline_keyboard'][0][0]['copy_text']['text']
        self.api.calls.clear()
        self.assertTrue(await self.ui.delivery.deliver(3, link.split('start=')[1]))
        kinds = [m for m,a in self.api.calls if m in ('copyMessage', 'sendMediaGroup')]
        self.assertEqual(kinds, ['sendMediaGroup', 'copyMessage', 'copyMessage', 'sendMediaGroup'])
        albums = [a for m,a in self.api.calls if m == 'sendMediaGroup']
        self.assertEqual([a['type'] for a in albums[0]['media']], ['photo', 'video'])
        self.assertEqual(albums[0]['media'][1]['caption'], 'Video caption')
        self.assertFalse(albums[0]['protect_content'])
        self.assertEqual(len(self.db.due(10**12)), 7)

    async def test_album_max_ten_and_old_links_still_copy(self):
        sources = []
        for i in range(12):
            self.db.content(99, -100123, i+1, {'type': 'photo', 'media': f'p{i}'})
            sources.append((-100123, i+1))
        key = self.db.link(99, 2, sources)
        await self.ui.delivery.deliver(3, key)
        albums = [a for m,a in self.api.calls if m == 'sendMediaGroup']
        self.assertEqual([len(a['media']) for a in albums], [10, 2])
        self.api.calls.clear()
        old = self.db.link(99, 2, [(-100123, 100), (-100123, 101)])
        await self.ui.delivery.deliver(3, old)
        self.assertEqual(len([m for m,a in self.api.calls if m == 'copyMessage']), 2)

    async def test_protection_menu_requires_explicit_owner_choice(self):
        await self.ui.callback(2, 's:protection', {})
        self.assertFalse(self.db.settings(99)['protection'])
        await self.ui.callback(2, 's:protect:1', {})
        self.assertTrue(self.db.settings(99)['protection'])
        with self.assertRaises(PermissionError):
            await self.ui.callback(3, 's:protect:0', {})

    async def test_back_cancel_expiry_do_not_upload_settings_text(self):
        await self.ui.callback(2, 's:welcome', {})
        await self.ui.callback(2, 's:back', {})
        self.assertNotIn(2, self.ui.pending)
        await self.ui.callback(2, 's:welcome', {})
        await self.ui.callback(2, 'x:cancel', {})
        self.assertNotIn(2, self.ui.pending)
        self.ui.wait(2, 'setting', key='welcome')
        self.ui.pending[2]['expires'] = 0
        await self.send('Late setting input')
        self.assertFalse(any(m == 'copyMessage' for m,a in self.api.calls))
        self.assertIn('Sesi pengaturan berakhir', next(args['text'] for method,args in reversed(self.api.calls) if method=='sendMessage'))

    async def test_master_back_clears_hash_and_cancel_discards_credentials(self):
        await self.master.begin(2)
        await self.master.message(2, {'text': '123'})
        await self.master.message(2, {'text': 'a'*32})
        await self.master.callback(2, 'm:back', {})
        self.assertEqual(self.master.pending[2]['step'], 'api_hash')
        self.assertNotIn('api_hash', self.master.pending[2])
        await self.master.callback(2, 'x:cancel', {})
        self.assertNotIn(2, self.master.pending)

    async def test_lists_use_names_and_detail_is_authorized(self):
        self.db.display_name(99, 'Cinema Room')
        await self.master.listing(2, 0)
        label = self.api.calls[-1][1]['reply_markup']['inline_keyboard'][0][0]['text']
        self.assertIn('Cinema Room', label)
        self.assertNotIn('ExampleBot', label)
        with self.assertRaises(PermissionError):
            await self.master.callback(3, 'm:detail:99:mine:0', {})

    async def test_revoke_requires_confirmation_and_owner(self):
        await self.master.callback(1, 'm:revoke', {})
        await self.master.message(1, {'text': '2'})
        self.assertTrue(self.db.allowed(2))
        with self.assertRaises(PermissionError):
            await self.master.callback(2, 'm:revoke_yes:2', {})
        await self.master.callback(1, 'm:revoke_yes:2', {})
        self.assertFalse(self.db.allowed(2))

    async def test_reopen_preserves_custom_settings_names_and_media(self):
        self.db.setting(99, 2, 'welcome', 'My custom welcome')
        self.db.content(99, -100123, 55, {'type': 'photo', 'media': 'p1'})
        self.db.display_name(99, 'Cinema Room')
        self.db.close()
        self.db = Store(self.path, self.key, 1)
        self.assertEqual(self.db.settings(99)['welcome'], 'My custom welcome')
        self.assertEqual(self.db.bot(99)['name'], 'Cinema Room')
        self.assertEqual(self.db.content(99, -100123, 55)['media'], 'p1')

    async def test_expired_confirmation_cannot_revoke_or_send_broadcast(self):
        await self.master.callback(1, 'm:revoke', {})
        await self.master.message(1, {'text': '2'})
        self.master.pending[1]['expires'] = 0
        await self.master.handle({'callback_query': {'id': 'expired', 'from': {'id': 1},
            'data': 'm:revoke_yes:2', 'message': {'chat': {'id': 1}, 'message_id': 1}}})
        self.assertTrue(self.db.allowed(2))
        await self.send('/broadcast')
        await self.send('Announcement')
        nonce = self.ui.pending[2]['nonce']
        self.ui.pending[2]['expires'] = 0
        await self.ui.handle({'callback_query': {'id': 'expired2', 'from': {'id': 2},
            'data': f's:send_broadcast:{nonce}', 'message': {'chat': {'id': 2}, 'message_id': 2}}})
        self.assertFalse(any(m == 'copyMessage' for m,a in self.api.calls))

    async def test_custom_old_default_is_not_replaced_on_every_restart(self):
        from subgate.store import DEFAULTS
        custom = 'Halo! Saya dapat menyimpan dan membagikan file melalui link.'
        self.db.setting(99, 2, 'welcome', custom)
        self.db.close()
        self.db = Store(self.path, self.key, 1)
        self.assertEqual(self.db.settings(99)['welcome'], custom)

    async def test_album_does_not_bypass_membership_and_protection(self):
        self.db.target(99, 2, -1001, 'channel', 'https://t.me/a')
        self.db.setting(99, 2, 'protection', True)
        for i in (1, 2):
            self.db.content(99, -100123, i, {'type':'photo', 'media':f'p{i}'})
        key = self.db.link(99, 2, [(-100123, 1), (-100123, 2)])
        self.api.members[(-1001, 3)] = 'left'
        self.assertFalse(await self.ui.delivery.deliver(3, key))
        self.assertFalse(any(m == 'sendMediaGroup' for m,a in self.api.calls))
        self.api.members[(-1001, 3)] = 'member'
        self.assertTrue(await self.ui.delivery.deliver(3, key))
        self.assertTrue(next(a for m,a in self.api.calls if m == 'sendMediaGroup')['protect_content'])

    async def test_photo_welcome_with_long_personalized_text_does_not_exceed_caption_limit(self):
        self.db.setting(99, 2, 'welcome_photo', {'file_id':'p1'})
        self.db.setting(99, 2, 'welcome', 'A'*980+'{nama_pengguna}')
        self.ui.names[2] = 'X'*100
        await self.ui.welcome(2)
        photo = next(a for m,a in self.api.calls if m == 'sendPhoto')
        self.assertLessEqual(len(photo['caption']), 1024)

    async def test_missing_name_of_inactive_bot_is_fetched_and_cached(self):
        calls = []
        async def lookup(bot):
            calls.append(bot)
            return 'Recovered Name'
        self.manager.lookup_name = lookup
        self.db.display_name(99, '')
        await self.master.listing(2, 0)
        self.assertEqual(calls, [99])
        self.assertEqual(self.db.bot(99)['name'], 'Recovered Name')
        label = self.api.calls[-1][1]['reply_markup']['inline_keyboard'][0][0]['text']
        self.assertIn('Recovered Name', label)

    async def test_legacy_schema_migration_retains_links_jobs_credentials_and_custom_text(self):
        import json
        import sqlite3
        legacy_path = Path(self.tmp.name)/'legacy'
        conn = sqlite3.connect(legacy_path)
        conn.executescript("""
          CREATE TABLE bots(id INTEGER PRIMARY KEY, owner INTEGER NOT NULL,
             username TEXT NOT NULL, credentials BLOB NOT NULL,
             active INTEGER NOT NULL DEFAULT 1, settings TEXT NOT NULL DEFAULT '{}');
          CREATE TABLE links(bot INTEGER NOT NULL, key TEXT NOT NULL,
             sources TEXT NOT NULL, PRIMARY KEY(bot,key));
          CREATE TABLE jobs(id INTEGER PRIMARY KEY, bot INTEGER NOT NULL,
             chat INTEGER NOT NULL, message_id INTEGER NOT NULL, due REAL NOT NULL,
             UNIQUE(bot,chat,message_id));
        """)
        old = {'database': -100123, 'welcome': 'Halo! Saya dapat menyimpan dan membagikan file melalui link.',
               'force_message': 'Custom instructions', 'delete_notice': 'File akan dihapus otomatis dalam {durasi}.'}
        conn.execute('INSERT INTO bots VALUES (99,2,?,?,1,?)',
                     ('ExampleBot', self.db.bot(99)['credentials'], json.dumps(old)))
        conn.execute('INSERT INTO links VALUES (99,?,?)', ('legacy', '[[-100123,7]]'))
        conn.execute('INSERT INTO jobs VALUES (1,99,3,123,100)')
        conn.commit()
        conn.close()
        migrated = Store(legacy_path, self.key, 1)
        try:
            self.assertEqual(migrated.sources(99, 'legacy'), [(-100123,7)])
            self.assertEqual(migrated.due(101)[0]['message_id'], 123)
            self.assertEqual(migrated.credentials(99)['token'], 'token')
            self.assertEqual(migrated.settings(99)['force_message'], 'Custom instructions')
            self.assertIn('Selamat datang', migrated.settings(99)['welcome'])
        finally:
            migrated.close()
