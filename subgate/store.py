"""Durable bot ownership, settings and jobs. No Telegram network calls here."""
import json
import secrets
import sqlite3
from pathlib import Path

from cryptography.fernet import Fernet

DEFAULTS = {
    'database': None, 'protection': False, 'delete_seconds': 1800,
    'welcome': '✦ Selamat datang di {nama_bot} ✨\n\nHai, {nama_pengguna} 👋\nPunya link konten? Buka linknya untuk mengambil isi yang dibagikan.',
    'welcome_photo': None,
    'force_message': '✦ Tinggal selangkah lagi 🔐\n\nGabung ke channel atau grup di bawah untuk membuka kontennya.\nSetelah selesai, tekan Coba Lagi, ya.',
    'delete_notice': '✦ Kontenmu sudah sampai 📦\n\nPesan di atas akan dihapus otomatis dalam {durasi}.\nNikmati kontennya sebelum waktunya habis, ya ✨',
}


class Store:
    def __init__(self, path, key, master_owner):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.cipher = Fernet(key)
        self.master_owner = int(master_owner)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript('''
            PRAGMA journal_mode=WAL;
            PRAGMA foreign_keys=ON;
            CREATE TABLE IF NOT EXISTS creators (id INTEGER PRIMARY KEY, allowed INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS bots (
                id INTEGER PRIMARY KEY, owner INTEGER NOT NULL, username TEXT NOT NULL,
                credentials BLOB NOT NULL, active INTEGER NOT NULL DEFAULT 1,
                settings TEXT NOT NULL DEFAULT '{}');
            CREATE TABLE IF NOT EXISTS admins (
                bot INTEGER NOT NULL REFERENCES bots(id), user INTEGER NOT NULL,
                PRIMARY KEY(bot,user));
            CREATE TABLE IF NOT EXISTS targets (
                bot INTEGER NOT NULL REFERENCES bots(id), chat INTEGER NOT NULL,
                kind TEXT NOT NULL, url TEXT NOT NULL, PRIMARY KEY(bot,chat));
            CREATE TABLE IF NOT EXISTS links (
                bot INTEGER NOT NULL REFERENCES bots(id), key TEXT NOT NULL,
                sources TEXT NOT NULL, PRIMARY KEY(bot,key));
            CREATE TABLE IF NOT EXISTS users (
                bot INTEGER NOT NULL REFERENCES bots(id), user INTEGER NOT NULL,
                PRIMARY KEY(bot,user));
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY, bot INTEGER NOT NULL REFERENCES bots(id),
                chat INTEGER NOT NULL, message_id INTEGER NOT NULL, due REAL NOT NULL,
                UNIQUE(bot,chat,message_id));
            CREATE TABLE IF NOT EXISTS content (
                bot INTEGER NOT NULL REFERENCES bots(id), chat INTEGER NOT NULL,
                message_id INTEGER NOT NULL, metadata TEXT NOT NULL,
                PRIMARY KEY(bot,chat,message_id));
            CREATE TABLE IF NOT EXISTS incidents (
                bot INTEGER NOT NULL, scope TEXT NOT NULL, PRIMARY KEY(bot,scope));
        ''')
        columns = {row['name'] for row in self.conn.execute('PRAGMA table_info(bots)')}
        if 'redeploy_required' not in columns:
            self.conn.execute('ALTER TABLE bots ADD COLUMN redeploy_required INTEGER NOT NULL DEFAULT 0')
            self.conn.commit()

        if 'name' not in columns:
            self.conn.execute("ALTER TABLE bots ADD COLUMN name TEXT NOT NULL DEFAULT ''")
            self.conn.commit()
        target_columns = {r['name'] for r in self.conn.execute('PRAGMA table_info(targets)')}
        if 'title' not in target_columns:
            self.conn.execute("ALTER TABLE targets ADD COLUMN title TEXT NOT NULL DEFAULT ''")
            self.conn.commit()
        # Old settings were stored as full snapshots; update only unchanged defaults.
        old_defaults = {
            'welcome': 'Halo! Saya dapat menyimpan dan membagikan file melalui link.',
            'force_message': 'Silakan bergabung ke semua channel/grup berikut untuk mengambil file.',
            'delete_notice': 'File akan dihapus otomatis dalam {durasi}.',
        }
        if self.conn.execute('PRAGMA user_version').fetchone()[0] < 1:
            with self.conn:
                for row in self.rows('SELECT id,settings FROM bots'):
                    saved = json.loads(row['settings'])
                    for key, old in old_defaults.items():
                        if saved.get(key) == old:
                            saved[key] = DEFAULTS[key]
                    self.conn.execute('UPDATE bots SET settings=? WHERE id=?', (json.dumps(saved), row['id']))

            self.conn.execute('PRAGMA user_version=1')

    def display_name(self, bot, name):
        with self.conn:
            self.conn.execute('UPDATE bots SET name=? WHERE id=?', (name, bot))

    def content(self, bot, chat, message_id, metadata=None):
        if metadata is not None:
            with self.conn:
                self.conn.execute('INSERT INTO content VALUES (?,?,?,?) ON CONFLICT(bot,chat,message_id) DO UPDATE SET metadata=excluded.metadata',
                                  (bot, chat, message_id, json.dumps(metadata)))
        rows = self.rows('SELECT metadata FROM content WHERE bot=? AND chat=? AND message_id=?', (bot, chat, message_id))
        return json.loads(rows[0]['metadata']) if rows else None

    def close(self):
        self.conn.close()

    def rows(self, sql, args=()):
        return [dict(row) for row in self.conn.execute(sql, args)]

    def master(self, actor):
        if actor != self.master_owner:
            raise PermissionError('Hanya pemilik bot induk yang boleh melakukan ini.')

    def allowed(self, user):
        if user == self.master_owner:
            return True
        rows = self.rows('SELECT allowed FROM creators WHERE id=?', (user,))
        return bool(rows and rows[0]['allowed'])

    def grant(self, actor, user):
        self.master(actor)
        if user <= 0:
            raise ValueError('ID pengguna harus positif.')
        with self.conn:
            self.conn.execute('INSERT INTO creators VALUES (?,1) ON CONFLICT(id) DO UPDATE SET allowed=1', (user,))

    def revoke(self, actor, user):
        self.master(actor)
        if user == self.master_owner:
            raise ValueError('Tidak dapat mencabut izin pemilik bot induk.')
        with self.conn:
            self.conn.execute('INSERT INTO creators VALUES (?,0) ON CONFLICT(id) DO UPDATE SET allowed=0', (user,))
            self.conn.execute('UPDATE bots SET active=0, redeploy_required=1 WHERE owner=?', (user,))

    def creators(self):
        return self.rows('SELECT * FROM creators ORDER BY id')

    def bot(self, bot):
        rows = self.rows('SELECT * FROM bots WHERE id=?', (bot,))
        if not rows:
            raise ValueError('Bot belum terdaftar.')
        return rows[0]

    def bots(self, owner=None):
        if owner is None:
            return self.rows('SELECT * FROM bots ORDER BY id')
        return self.rows('SELECT * FROM bots WHERE owner=? ORDER BY id', (owner,))

    def owner(self, bot, actor):
        if self.bot(bot)['owner'] != actor:
            raise PermissionError('Hanya pemilik bot yang boleh mengubah pengaturan.')

    def deploy(self, actor, bot, username, api_id, api_hash, token, session, name=None):
        if not self.allowed(actor):
            raise PermissionError('Kamu belum mendapat izin membuat bot.')
        existing = self.rows('SELECT owner FROM bots WHERE id=?', (bot,))
        if existing and existing[0]['owner'] != actor:
            raise PermissionError('Bot sudah terdaftar milik pengguna lain.')
        encrypted = self.cipher.encrypt(json.dumps(dict(
            api_id=api_id, api_hash=api_hash, token=token, session=session)).encode())
        with self.conn:
            self.conn.execute('''INSERT INTO bots(id,owner,username,credentials,active)
                VALUES (?,?,?,?,1) ON CONFLICT(id) DO UPDATE SET
                username=excluded.username, credentials=excluded.credentials, active=1, redeploy_required=0''',
                (bot, actor, username, encrypted))

        if name:
            self.display_name(bot, name)

    def credentials(self, bot):
        return json.loads(self.cipher.decrypt(self.bot(bot)['credentials']))

    def set_active(self, actor, bot, active):
        self.master(actor)
        if active and not self.allowed(self.bot(bot)['owner']):
            raise PermissionError('Pemilik bot belum mendapat izin.')
        if active and self.bot(bot)['redeploy_required']:
            raise PermissionError('Bot ini perlu deploy ulang melalui /buatbot setelah pencabutan izin.')
        with self.conn:
            self.conn.execute('UPDATE bots SET active=? WHERE id=?', (bool(active), bot))

    def settings(self, bot):
        return DEFAULTS | json.loads(self.bot(bot)['settings'])

    def setting(self, bot, actor, name, value):
        self.owner(bot, actor)
        if name not in DEFAULTS:
            raise ValueError('Pengaturan tidak dikenal.')
        if name == 'database' and (not isinstance(value, int) or value >= 0):
            raise ValueError('Gunakan ID channel negatif.')
        if name == 'protection' and not isinstance(value, bool):
            raise ValueError('Proteksi harus aktif/nonaktif.')
        if name == 'delete_seconds' and (type(value) is not int or not 0 <= value <= 172740):
            raise ValueError('Durasi 0 (nonaktif) sampai 2879 menit; Telegram membatasi penghapusan pesan hingga 48 jam.')
        if name in ('welcome', 'force_message', 'delete_notice'):
            if not isinstance(value, str) or not value.strip() or len(value) > 1000:
                raise ValueError('Teks harus berisi 1–1000 karakter.')
        if name == 'delete_notice':
            import string
            for _, field, spec, conversion in string.Formatter().parse(value):
                if field is not None and (field != 'durasi' or spec or conversion):
                    raise ValueError('Hanya penanda {durasi} yang diperbolehkan.')
        if name == 'welcome_photo' and value is not None and not isinstance(value, dict):
            raise ValueError('Kirim foto untuk pesan sambutan.')
        settings = self.settings(bot)
        settings[name] = value
        with self.conn:
            self.conn.execute('UPDATE bots SET settings=? WHERE id=?', (json.dumps(settings), bot))

    def admins(self, bot):
        return [r['user'] for r in self.rows('SELECT user FROM admins WHERE bot=? ORDER BY user', (bot,))]

    def admin(self, bot, actor, user, add):
        self.owner(bot, actor)
        if user <= 0:
            raise ValueError('ID pengguna harus positif.')
        with self.conn:
            if add:
                self.conn.execute('INSERT OR IGNORE INTO admins VALUES (?,?)', (bot, user))
            else:
                self.conn.execute('DELETE FROM admins WHERE bot=? AND user=?', (bot, user))

    def can_upload(self, bot, user):
        return user == self.bot(bot)['owner'] or user in self.admins(bot)

    def targets(self, bot):
        return self.rows('SELECT * FROM targets WHERE bot=? ORDER BY rowid', (bot,))

    def target(self, bot, actor, chat, kind, url, title=''):
        self.owner(bot, actor)
        targets = self.targets(bot)
        if chat not in [r['chat'] for r in targets] and len(targets) >= 4:
            raise ValueError('Maksimal 4 channel/grup ForceSubs.')
        if kind not in ('channel', 'group') or chat >= 0 or not url.startswith('https://t.me/'):
            raise ValueError('Channel/grup tidak valid.')
        with self.conn:
            self.conn.execute('''INSERT INTO targets(bot,chat,kind,url,title) VALUES (?,?,?,?,?)
                ON CONFLICT(bot,chat) DO UPDATE SET kind=excluded.kind,url=excluded.url,title=excluded.title''',
                (bot, chat, kind, url, title))

    def remove_target(self, bot, actor, chat):
        self.owner(bot, actor)
        with self.conn:
            self.conn.execute('DELETE FROM targets WHERE bot=? AND chat=?', (bot, chat))
            self.conn.execute('DELETE FROM incidents WHERE bot=? AND scope=?', (bot, f'chat:{chat}'))

    def link(self, bot, actor, sources):
        if not self.can_upload(bot, actor):
            raise PermissionError('Hanya pemilik dan admin yang dapat membuat link.')
        if not sources:
            raise ValueError('Batch belum berisi file.')
        key = secrets.token_urlsafe(18)
        with self.conn:
            self.conn.execute('INSERT INTO links VALUES (?,?,?)', (bot, key, json.dumps(sources)))
        return key

    def sources(self, bot, key):
        rows = self.rows('SELECT sources FROM links WHERE bot=? AND key=?', (bot, key))
        return [tuple(item) for item in json.loads(rows[0]['sources'])] if rows else []

    def add_user(self, bot, user):
        with self.conn:
            self.conn.execute('INSERT OR IGNORE INTO users VALUES (?,?)', (bot, user))

    def users(self, bot):
        return [r['user'] for r in self.rows('SELECT user FROM users WHERE bot=?', (bot,))]

    def schedule(self, bot, chat, message_id, due):
        with self.conn:
            self.conn.execute('INSERT OR IGNORE INTO jobs(bot,chat,message_id,due) VALUES (?,?,?,?)',
                              (bot, chat, message_id, due))

    def due(self, now, bot=None):
        if bot is not None:
            return self.rows('SELECT * FROM jobs WHERE due<=? AND bot=? ORDER BY due LIMIT 100', (now, bot))
        return self.rows('SELECT * FROM jobs WHERE due<=? ORDER BY due LIMIT 100', (now,))

    def finish_job(self, job):
        with self.conn:
            self.conn.execute('DELETE FROM jobs WHERE id=?', (job,))

    def retry_job(self, job, due):
        with self.conn:
            self.conn.execute('UPDATE jobs SET due=? WHERE id=?', (due, job))

    def incident(self, bot, scope, broken):
        exists = bool(self.rows('SELECT 1 FROM incidents WHERE bot=? AND scope=?', (bot, scope)))
        with self.conn:
            if broken:
                self.conn.execute('INSERT OR IGNORE INTO incidents VALUES (?,?)', (bot, scope))
            else:
                self.conn.execute('DELETE FROM incidents WHERE bot=? AND scope=?', (bot, scope))
        return exists != broken

    def incidents(self):
        return self.rows('SELECT * FROM incidents')
