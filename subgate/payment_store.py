"""Persistent packages, orders and fulfillment; shared SQLite, no network calls."""
import json
import secrets
import time


def migrate(db):
    cols = {r['name'] for r in db.conn.execute('PRAGMA table_info(bots)')}
    if 'kind' not in cols:
        db.conn.execute("ALTER TABLE bots ADD COLUMN kind TEXT NOT NULL DEFAULT 'forcesubs'")
    db.conn.executescript('''
        CREATE TABLE IF NOT EXISTS creator_permissions (
            user INTEGER NOT NULL, kind TEXT NOT NULL, allowed INTEGER NOT NULL,
            PRIMARY KEY(user,kind));
        CREATE TABLE IF NOT EXISTS payment_accounts (
            owner INTEGER PRIMARY KEY, username TEXT NOT NULL, recipient TEXT NOT NULL,
            secret BLOB NOT NULL, route TEXT NOT NULL UNIQUE, enabled INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS payment_packages (
            id INTEGER PRIMARY KEY, bot INTEGER NOT NULL REFERENCES bots(id),
            name TEXT NOT NULL, description TEXT NOT NULL, price INTEGER NOT NULL,
            target INTEGER NOT NULL, photo TEXT, status TEXT NOT NULL DEFAULT 'active');
        CREATE TABLE IF NOT EXISTS payment_orders (
            id TEXT PRIMARY KEY, bot INTEGER NOT NULL REFERENCES bots(id), buyer INTEGER NOT NULL,
            owner INTEGER NOT NULL, package INTEGER NOT NULL, name TEXT NOT NULL, target INTEGER NOT NULL,
            price INTEGER NOT NULL, recipient TEXT NOT NULL, total INTEGER,
            transaction_id TEXT UNIQUE, qr BLOB, state TEXT NOT NULL DEFAULT 'pending',
            payment TEXT NOT NULL DEFAULT 'pending', delivery TEXT NOT NULL DEFAULT 'ready',
            invite BLOB, invite_name TEXT, used INTEGER NOT NULL DEFAULT 0,
            revoked INTEGER NOT NULL DEFAULT 0, notified INTEGER NOT NULL DEFAULT 0,
            delivered INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL, checked REAL NOT NULL DEFAULT 0);
        CREATE INDEX IF NOT EXISTS payment_order_bot ON payment_orders(bot,buyer,created);
        CREATE TABLE IF NOT EXISTS payment_events (
            transaction_id TEXT PRIMARY KEY, owner INTEGER NOT NULL, amount INTEGER NOT NULL, created REAL NOT NULL);
        INSERT OR IGNORE INTO creator_permissions SELECT id,'forcesubs',allowed FROM creators;
    ''')
    columns={r['name'] for r in db.conn.execute('PRAGMA table_info(payment_orders)')}
    if 'work_due' not in columns:
        db.conn.execute('ALTER TABLE payment_orders ADD COLUMN work_due REAL NOT NULL DEFAULT 0')
    for name,definition in {'buyer_name':"TEXT NOT NULL DEFAULT ''",'target_kind':"TEXT NOT NULL DEFAULT ''"}.items():
        if name not in columns: db.conn.execute('ALTER TABLE payment_orders ADD COLUMN '+name+' '+definition)
    package_columns={r['name'] for r in db.conn.execute('PRAGMA table_info(payment_packages)')}
    if 'position' not in package_columns:
        db.conn.execute('ALTER TABLE payment_packages ADD COLUMN position INTEGER NOT NULL DEFAULT 0')
        db.conn.execute('UPDATE payment_packages SET position=id')
    db.conn.executescript('\n        CREATE TABLE IF NOT EXISTS payment_started(bot INTEGER NOT NULL,user INTEGER NOT NULL,PRIMARY KEY(bot,user));\n        CREATE TABLE IF NOT EXISTS payment_qr_messages(bot INTEGER NOT NULL,order_id TEXT NOT NULL,chat INTEGER NOT NULL,message_id INTEGER NOT NULL,cleared INTEGER NOT NULL DEFAULT 0,next_try REAL NOT NULL DEFAULT 0,PRIMARY KEY(bot,chat,message_id));\n    ')
    for row in db.rows('SELECT id,settings FROM bots WHERE kind=?',('payment',)):
        values=json.loads(row['settings'])
        if values.get('payment_welcome')=='Selamat datang ✨\nPilih paket untuk membuka aksesmu.':
            values['payment_welcome']='Hai, {nama_pengguna} 👋\nPilih akses favoritmu dan dapatkan aksesnya dengan mudah 🤍'
            db.conn.execute('UPDATE bots SET settings=? WHERE id=?',(json.dumps(values),row['id']))
    db.conn.commit()


class MinimumPriceError(ValueError): pass


class PaymentStore:
    def __init__(self, db):
        self.db, self.conn = db, db.conn

    def seal(self, value):
        return self.db.cipher.encrypt(value.encode()) if value else None

    def open(self, value):
        return self.db.cipher.decrypt(value).decode() if value else None

    def account(self, owner, username=None, recipient=None, key=None, enabled=False):
        if username is not None:
            old = self.account(owner)
            if old and old['recipient'] != recipient and self.db.rows(
                "SELECT 1 FROM payment_orders WHERE owner=? AND payment='pending' LIMIT 1", (owner,)):
                raise ValueError('Masih ada transaksi belum terselesaikan pada akun lama.')
            route = old['route'] if old else secrets.token_urlsafe(32)
            stored_key=old['key'] if old and old['recipient']==recipient and key is None else (key or '')
            with self.conn:
                self.conn.execute('''INSERT INTO payment_accounts VALUES (?,?,?,?,?,?)
                    ON CONFLICT(owner) DO UPDATE SET username=excluded.username,recipient=excluded.recipient,
                    secret=excluded.secret,enabled=excluded.enabled''',
                    (owner,username,recipient,self.db.cipher.encrypt(stored_key.encode()),route,enabled))
        rows = self.db.rows('SELECT * FROM payment_accounts WHERE owner=?', (owner,))
        if not rows: return None
        row = rows[0]
        row['key'] = self.open(row.pop('secret'))
        return row

    def packages(self, bot, owner=False):
        return self.db.rows("SELECT * FROM payment_packages WHERE bot=? AND status != 'deleted'" +
                            ('' if owner else " AND status='active'") + ' ORDER BY position,id', (bot,))

    def package(self, bot, ident):
        rows = self.db.rows('SELECT * FROM payment_packages WHERE bot=? AND id=?', (bot,ident))
        if not rows: raise ValueError('Akses ini sedang tidak tersedia. Pilih akses lainnya, ya 🤍')
        return rows[0]

    def save_package(self, bot, actor, ident=None, **values):
        self.staff(bot,actor)
        if actor!=self.db.bot(bot)['owner'] and (ident is None or not set(values)<= {'name','description','photo'}):
            raise PermissionError('Admin hanya boleh mengubah nama, deskripsi dan foto akses.')
        if self.db.bot(bot)['kind'] != 'payment': raise ValueError('Bukan bot Payment.')
        base = self.package(bot,ident) if ident else dict(name='',description='',price=0,target=0,photo=None)
        base.update(values)
        if type(base['price']) is int and base['price']<1000: raise MinimumPriceError('Harga minimal Rp1.000')
        if (not isinstance(base['name'],str) or not 1 <= len(base['name'].strip()) <= 80 or
            not isinstance(base['description'],str) or len(base['description']) > 1000 or
            type(base['price']) is not int or not 1000 <= base['price'] <= 100_000_000 or
            type(base['target']) is not int or base['target'] >= 0):
            raise ValueError('Nama 1–80 karakter, deskripsi maksimal 1000, harga positif, ID target negatif.')
        if base['photo'] is not None and not isinstance(base['photo'],str): raise ValueError('Foto tidak valid.')
        if type(base['price']) is int and base['price']<1000: raise MinimumPriceError('Harga minimal Rp1.000')
        args = tuple(base[k] for k in ('name','description','price','target','photo'))
        with self.conn:
            if ident:
                self.conn.execute('UPDATE payment_packages SET name=?,description=?,price=?,target=?,photo=? WHERE bot=? AND id=?', (*args,bot,ident))
            else:
                ident = self.conn.execute('INSERT INTO payment_packages(name,description,price,target,photo,bot) VALUES (?,?,?,?,?,?)', (*args,bot)).lastrowid
                position=self.conn.execute('SELECT COALESCE(MAX(position),0)+1 FROM payment_packages WHERE bot=?',(bot,)).fetchone()[0]
                self.conn.execute('UPDATE payment_packages SET position=? WHERE id=?',(position,ident))
        return ident

    def package_status(self, bot, actor, ident, status):
        self.db.owner(bot,actor)
        if status not in ('active','inactive','deleted'): raise ValueError('Status tidak valid.')
        self.package(bot,ident)
        with self.conn:
            self.conn.execute('UPDATE payment_packages SET status=? WHERE bot=? AND id=?', (status,bot,ident))
            if status != 'active':
                self.conn.execute("UPDATE payment_orders SET state='cancelled' WHERE bot=? AND package=? AND state='pending' AND payment='pending'", (bot,ident))

    def new_order(self, bot, buyer, package, buyer_name="", target_kind=""):
        record = self.db.bot(bot)
        p = self.package(bot,package)
        account = self.account(record['owner'])
        if not record['active'] or not self.db.allowed(record['owner'],'payment'):
            raise ValueError('Bot sedang tidak aktif.')
        if p['price']<1000: raise MinimumPriceError('Harga minimal Rp1.000')
        if p['status'] != 'active': raise ValueError('Akses ini sedang tidak tersedia. Pilih akses lainnya, ya 🤍')
        if not account or not account['enabled']: raise ValueError('Pembayaran belum disiapkan pemilik.')
        ident = secrets.token_hex(12)
        with self.conn:
            self.conn.execute('''INSERT INTO payment_orders(id,bot,buyer,owner,package,name,target,price,recipient,created,buyer_name,target_kind)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''', (ident,bot,buyer,record['owner'],package,p['name'],p['target'],p['price'],account['recipient'],time.time(),buyer_name,target_kind))
        return self.order(bot,ident)

    def order(self, bot, ident, buyer=None):
        rows = self.db.rows('SELECT * FROM payment_orders WHERE bot=? AND id=?', (bot,ident))
        if not rows: raise ValueError('Pesanan tidak ditemukan.')
        row = rows[0]
        if buyer is not None and row['buyer'] != buyer: raise PermissionError('Pesanan bukan milikmu.')
        row['qr'] = self.open(row['qr'])
        row['invite'] = self.open(row['invite'])
        return row

    def attach(self, ident, transaction, qr, total):
        with self.conn:
            self.conn.execute('UPDATE payment_orders SET transaction_id=?,qr=?,total=? WHERE id=? AND transaction_id IS NULL',
                              (transaction,self.seal(qr),total,ident))
        events=self.db.rows('SELECT owner,amount FROM payment_events WHERE transaction_id=?',(transaction,))
        if events:
            self.accept(events[0]['owner'],transaction,events[0]['amount'])

    def cancel(self, bot, buyer, ident):
        self.order(bot,ident,buyer)
        with self.conn:
            self.conn.execute("UPDATE payment_orders SET state='cancelled' WHERE bot=? AND id=? AND payment='pending'", (bot,ident))

    def accept(self, owner, transaction, amount):
        rows = self.db.rows('SELECT * FROM payment_orders WHERE owner=? AND transaction_id=?', (owner,transaction))
        if not rows:
            # A callback can beat the create-payment HTTP response. Persist it
            # after signature verification; attach() will reconcile the ID.
            if type(amount) is not int or amount <= 0: raise ValueError('Nominal tidak valid.')
            with self.conn:
                self.conn.execute('INSERT OR IGNORE INTO payment_events VALUES (?,?,?,?)',(transaction,owner,amount,time.time()))
            return 'unmatched'
        order = rows[0]
        if type(amount) is not int or amount != order['price']: raise ValueError('Nominal callback tidak cocok.')
        account = self.account(owner)
        if not account or account['recipient'] != order['recipient']: raise ValueError('Penerima berubah.')
        record = self.db.bot(order['bot'])
        status = 'verified' if (order['state']=='pending' and record['active'] and self.db.allowed(owner,'payment')) else 'late'
        with self.conn:
            cur = self.conn.execute('INSERT OR IGNORE INTO payment_events VALUES (?,?,?,?)', (transaction,owner,amount,time.time()))
            if not cur.rowcount:
                previous=self.db.rows('SELECT owner,amount FROM payment_events WHERE transaction_id=?',(transaction,))[0]
                if previous['owner']!=owner or previous['amount']!=amount: raise ValueError('Transaksi sudah terikat ke akun/nominal lain.')
                if order['payment']!='pending': return 'duplicate'
            self.conn.execute('UPDATE payment_orders SET payment=? WHERE id=?', (status,order['id']))
        return status

    def update(self, bot, ident, **values):
        allowed = {'delivery','invite','invite_name','used','revoked','notified','delivered','checked','work_due','buyer_name','target_kind'}
        if not values or not set(values) <= allowed: raise ValueError('Field tidak valid.')
        if 'invite' in values: values['invite'] = self.seal(values['invite'])
        with self.conn:
            self.conn.execute('UPDATE payment_orders SET '+','.join(k+'=?' for k in values)+' WHERE bot=? AND id=?', (*values.values(),bot,ident))

    def history(self, bot, buyer):
        return self.db.rows("SELECT id,name,price,total,created,used,delivery FROM payment_orders WHERE bot=? AND buyer=? AND payment='verified' ORDER BY created DESC", (bot,buyer))

    def pending(self, bot, now, limit=20):
        return self.db.rows("SELECT id FROM payment_orders WHERE bot=? AND transaction_id IS NOT NULL AND payment='pending' AND checked<=? ORDER BY checked,created LIMIT ?", (bot,now-30,limit))

    def work(self, bot):
        return self.db.rows("SELECT id FROM payment_orders WHERE bot=? AND work_due<=? AND ((payment='verified' AND (delivered=0 OR notified=0 OR (used=1 AND revoked=0))) OR (payment='late' AND notified=0)) ORDER BY work_due,created LIMIT 30", (bot,time.time()))

    def staff(self,bot,actor):
        if actor!=self.db.bot(bot)['owner'] and actor not in self.db.admins(bot):
            raise PermissionError('Pengaturan hanya tersedia untuk owner dan admin.')

    def mark_started(self,bot,user):
        with self.conn:
            self.conn.execute('INSERT OR IGNORE INTO payment_started VALUES (?,?)',(bot,user))
        self.db.add_user(bot,user)

    def started(self,bot,user):
        return bool(self.db.rows('SELECT 1 FROM payment_started WHERE bot=? AND user=?',(bot,user)))

    def move(self,bot,actor,ident,direction):
        self.db.owner(bot,actor)
        if direction not in (-1,1): raise ValueError('Arah tidak valid.')
        rows=self.packages(bot,True)
        index=next((i for i,row in enumerate(rows) if row['id']==ident),None)
        if index is None: raise ValueError('Akses tidak ditemukan.')
        other=index+direction
        if not 0<=other<len(rows): return
        rows[index],rows[other]=rows[other],rows[index]
        with self.conn:
            self.conn.executemany('UPDATE payment_packages SET position=? WHERE bot=? AND id=?',[(i,bot,row['id']) for i,row in enumerate(rows)])

    def qr_message(self,bot,ident,chat,message):
        self.order(bot,ident,chat)
        with self.conn:
            self.conn.execute('INSERT OR IGNORE INTO payment_qr_messages(bot,order_id,chat,message_id) VALUES (?,?,?,?)',(bot,ident,chat,message))

    def qr_due(self,bot):
        return self.db.rows("SELECT q.* FROM payment_qr_messages q JOIN payment_orders o ON o.id=q.order_id AND o.bot=q.bot WHERE q.bot=? AND q.cleared=0 AND q.next_try<=? AND (o.state='cancelled' OR o.payment='verified') ORDER BY q.next_try LIMIT 50",(bot,time.time()))
