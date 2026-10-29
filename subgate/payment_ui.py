"""Owner-only Payment settings and private customer checkout."""
import io
import re
from .ui_base import BaseUI, command
from .copy import h,panel,button,nav,link_button
from .service import inline
from .payment_store import PaymentStore,MinimumPriceError
from .service import TelegramFailure
from .broadcast import Broadcast
from .payment_service import PaymentService
from .saweria import Saweria

HOME=[button('⌂ Menu','p:home')]


class PaymentUI(BaseUI):
    def __init__(self,db,bot,api,public_base='',provider=None):
        super().__init__(db,api)
        self.bot=bot
        self.store=PaymentStore(db)
        self.provider=provider or Saweria(api.session)
        self.service=PaymentService(db,bot,api,self.provider)
        self.public_base=public_base
        self.checkouts={}
        self.broadcast=Broadcast(db,bot,api,self.is_staff,show=self.text,track_preview=self.track_broadcast_preview)

    async def track_broadcast_preview(self,user,message):
        if isinstance(message,dict) and 'message_id' in message:
            with self.db.conn:
                self.db.conn.execute('INSERT OR IGNORE INTO display_screens VALUES (?,?,?)',(self.bot,user,message['message_id']))

    def owner(self,user): self.db.owner(self.bot,user)
    def is_staff(self,user): return user==self.db.bot(self.bot)['owner'] or user in self.db.admins(self.bot)
    def staff(self,user): self.store.staff(self.bot,user)
    async def close(self):
        await self.broadcast.close()
        await super().close()
    def error_text(self,exc):
        if isinstance(exc,MinimumPriceError):
            return panel('💰 Harga minimal Rp1.000','Masukkan harga mulai dari Rp1.000 agar pembayaran bisa diproses, ya.')
        if 'tidak tersedia' in str(exc):
            return panel('Akses tidak tersedia','Akses ini sedang tidak tersedia. Pilih akses lainnya, ya 🤍')
        if 'saweria' in str(exc).lower() or 'QRIS' in str(exc):
            return panel('🔧 QRIS belum bisa disiapkan','Coba lagi sebentar, ya 🤍')
        return super().error_text(exc)
    def expiry_buttons(self,state): return [[button('⚙️ Pengaturan','p:settings')]]
    def error_buttons(self,user): return [[button('✖️ Batalkan','x:cancel')],HOME]
    async def cancelled(self,user):
        self.broadcast.cancel(user)
        self.clear(user)
        await self.text(user,panel('🍃 Dibatalkan','Perubahan belum disimpan.'),[HOME])

    async def handle(self,update):
        if 'chat_member' in update:
            await self.service.join(update['chat_member'])
            return
        await super().handle(update)

    async def photo_text(self,user,photo,text,buttons):
        return await super().photo_text(user,photo,text,buttons)

    async def home(self,user):
        self.clear(user)
        settings=self.db.settings(self.bot)
        buttons=[[button('🛍 Pilih Akses','p:list:0')],[button('🧾 Pembelian Saya','p:history:0')]]
        if self.is_staff(user): buttons.append([button('⚙️ Pengaturan','p:settings')])
        body=h(settings['payment_welcome'].replace('{nama_pengguna}',self.names.get(user,'teman')).replace('{nama_bot}',self.db.bot(self.bot).get('name') or 'botmu'))
        photo=settings.get('payment_photo')
        await self.photo_text(user,photo,panel('✨ Selamat datang di '+h(self.db.bot(self.bot).get('name') or 'botmu'),body),buttons)

    async def listing(self,user,page=0,manage=False):
        if manage: self.staff(user)
        self.clear(user)
        rows=self.store.packages(self.bot,manage)
        page=max(0,min(page,max(0,(len(rows)-1)//8)))
        buttons=[[button(p['name']+(' ⏸' if p['status']=='inactive' else ''),f'p:package:{p["id"]}:{int(manage)}')] for p in rows[page*8:(page+1)*8]]
        prefix='manage' if manage else 'list'
        moves=[]
        if page: moves.append(button('‹ Sebelumnya',f'p:{prefix}:{page-1}'))
        if (page+1)*8<len(rows): moves.append(button('Berikutnya ›',f'p:{prefix}:{page+1}'))
        if moves: buttons.append(moves)
        if manage and user==self.db.bot(self.bot)['owner']: buttons.append([button('＋ Tambah Akses','p:new')])
        buttons.append(HOME)
        await self.text(user,panel('✨ Pilih yang kamu suka','Ketuk salah satu akses untuk melihat detailnya 🤍') if rows else panel('🌙 Belum ada akses tersedia','Mampir lagi nanti, ya 🤍'),buttons)

    async def package(self,user,ident,manage=False):
        if manage: self.staff(user)
        p=self.store.package(self.bot,ident)
        if p['status']=='deleted' or (not manage and p['status']!='active'): raise ValueError('Akses tidak tersedia.')
        self.clear(user)
        body=f'{h(p["description"])}\n\n💰 Harga akses: <b>Rp{p["price"]:,}</b>\n🔑 Sekali beli, akses permanen untuk satu orang.'
        if manage:
            body+=f'\nTarget: {p["target"]}\nStatus: {h(p["status"])}'
            buttons=[[button(label,f'p:edit:{ident}:{field}') for label,field in pair] for pair in
                     ((('Nama','name'),('Deskripsi','description')),(('Harga','price'),('Target','target')),(('Foto','photo'),))]
            buttons += [[button('Aktifkan' if p['status']=='inactive' else 'Nonaktifkan',f'p:ask:{ident}:active' if p['status']=='inactive' else f'p:ask:{ident}:inactive'),button('Hapus',f'p:ask:{ident}:deleted')],[button('‹ Kembali','p:manage:0')]]
        else:
            buttons=[[button('💳 Beli Akses',f'p:buy:{ident}')],[button('‹ Kembali','p:list:0')]]
        if manage and user!=self.db.bot(self.bot)['owner']:
            body=f'{h(p["description"])}\n\n💰 Harga: Rp{p["price"]:,}'
            buttons=[[button('Nama',f'p:edit:{ident}:name'),button('Deskripsi',f'p:edit:{ident}:description')],[button('Foto',f'p:edit:{ident}:photo')],[button('‹ Kembali','p:manage:0')]]
        await self.photo_text(user,p['photo'],panel(h(p['name']),body),buttons)

    async def settings(self,user):
        self.staff(user); self.clear(user)
        buttons=[[button('Kelola Akses' if user==self.db.bot(self.bot)['owner'] else 'Edit Tampilan Akses','p:manage:0')],
                 [button('Sambutan','p:welcome_menu')],[button('📢 Broadcast','p:broadcast')]]
        if user==self.db.bot(self.bot)['owner']:
            buttons=[buttons[0],[button('Urutan Akses','p:sort:0')],[button('Saweria','p:account')],
                     [button('Admin','p:admins')],buttons[1],buttons[2]]
        await self.text(user,panel('⚙️ Atur botmu','Mau merapikan bagian mana?'),buttons+[HOME])

    async def history(self,user,page):
        rows=self.store.history(self.bot,user)
        page=max(0,min(page,max(0,(len(rows)-1)//8)))
        buttons=[[button(r['name'],f'p:access:{r["id"]}')] for r in rows[page*8:(page+1)*8]]
        moves=[]
        if page: moves.append(button('‹ Sebelumnya',f'p:history:{page-1}'))
        if (page+1)*8<len(rows): moves.append(button('Berikutnya ›',f'p:history:{page+1}'))
        if moves: buttons.append(moves)
        if not rows: buttons.append([button('🛍 Pilih Akses','p:list:0')])
        buttons.append(HOME)
        await self.text(user,panel('🧾 Koleksi aksesmu','Semua pembelian yang berhasil ada di sini.') if rows else panel('🧾 Belum ada koleksi','Akses yang sudah kamu beli akan muncul di sini 🤍'),buttons)

    async def callback(self,user,data,message):
        parts=data.split(':')
        if data=='p:home': return await self.home(user)
        if data.startswith('p:list:'): return await self.listing(user,int(parts[2]))
        if data.startswith('p:history:'): return await self.history(user,int(parts[2]))
        if data.startswith('p:package:'): return await self.package(user,int(parts[2]),bool(int(parts[3])))
        if data.startswith('p:access:'):
            order=self.store.order(self.bot,parts[2],user)
            if order['payment']!='verified': raise ValueError('Pembayaran belum terverifikasi.')
            order=self.store.order(self.bot,order['id'],user)
            price=f'{order["price"]:,}'.replace(',','.')
            body=f'📦 Akses: {h(order["name"])}\n💰 Harga: Rp{price}\n✅ Pembayaran berhasil'
            buttons=[]
            if order['used']: body+='\n\n🔒 Akses sudah digunakan\nLink ini sudah dipakai untuk bergabung.'
            elif order['invite']: buttons=[[self.service.access_button(order)]]
            else: body+='\n\nAkses sedang disiapkan.'
            if not order['used'] and not order['delivered']:
                buttons.append([button('🔄 Coba Kirim Link Lagi',f'p:retry:{order["id"]}')])
            result=await self.durable(user,panel('🧾 Detail Pembelian',body),buttons+[[button('‹ Pembelian Saya','p:history:0')]])
            await self.display.replace(self.bot,user,[])
            return result
        if data.startswith('p:retry:'):
            order=self.store.order(self.bot,parts[2],user)
            if order['payment']!='verified': raise ValueError('Pembayaran belum terverifikasi.')
            if not order['used'] and not order['delivered']:
                await self.service.fulfill(order['id'])
            return await self.callback(user,'p:access:'+order['id'],message)
        if data.startswith('p:buy:'):
            package=int(parts[2])
            p=self.store.package(self.bot,package)
            account=self.store.account(self.db.bot(self.bot)['owner'])
            if p['status']!='active': raise ValueError('Akses tidak aktif.')
            if not account or not account['enabled']:
                raise ValueError('Pembayaran percobaan belum disiapkan pemilik.')
            self.clear(user)
            import qrcode
            key=(package,message.get('message_id'))
            previous=self.checkouts.get(user)
            order=None
            if previous and previous['key']==key:
                if previous['order'] is None:
                    raise ValueError('Pembuatan QRIS tadi belum dapat dipastikan. Periksa transaksi sebelum mencoba dari detail akses baru.')
                saved=self.store.order(self.bot,previous['order'],user)
                if saved['state']=='pending' and saved['payment']=='pending': order=saved
            if order is None:
                self.checkouts[user]={'key':key,'order':None}
                await self.text(user,panel('💳 Menyiapkan QRIS…','Sebentar ya, pembayaranmu sedang disiapkan ✨'))
                order=await self.service.create(user,package,self.names.get(user,'Pembeli'),None)
                self.checkouts[user]['order']=order['id']
            if order['payment']=='verified':
                await self.service.fulfill(order['id'])
                return await self.text(user,'Pembayaran sudah terverifikasi. Periksa Pembelian Saya.',[HOME])
            if not self.db.bot(self.bot)['active'] or order['state']!='pending':
                return await self.text(user,'Pesanan sudah dibatalkan; jangan membayar QRIS sebelumnya.',[HOME])
            buffer=io.BytesIO()
            qrcode.make(order['qr']).save(buffer,format='PNG')
            rupiah=lambda value:f'{value:,}'.replace(',','.')
            caption=('💳 Tinggal selangkah lagi\n\n'
                     f'📦 Akses: {order["name"]}\n💰 Harga: Rp{rupiah(order["price"])}\n'
                     f'🧾 Biaya pembayaran: Rp{rupiah(order["total"]-order["price"])}\n💳 Total: Rp{rupiah(order["total"])}\n\n'
                     'Scan QRIS di atas. Setelah pembayaran terkonfirmasi, link aksesmu akan dikirim otomatis 🤍')
            buttons=[[button('🔎 Cek Pembayaran',f'p:check:{order["id"]}')],[button('✖️ Batalkan',f'p:cancel:{order["id"]}')]]
            try:
                result=await self.api.send_photo_bytes(user,buffer.getvalue(),caption,inline(buttons))
                self.store.qr_message(self.bot,order['id'],user,result['message_id'])
                await self.display.replace(self.bot,user,[])
                await self.service.cleanup_qr(order['id'])
            except Exception:
                self.store.cancel(self.bot,user,order['id'])
                raise
            return
        if data=='p:pay':
            self.clear(user)
            return await self.text(user,'Buka detail akses, lalu tekan Beli Akses. Sekarang QRIS dibuat langsung tanpa mengisi email.',[HOME])
        if data.startswith('p:check:'):
            ident=parts[2]
            controls=[[button('🔄 Cek Lagi',f'p:check:{ident}')],[button('✖️ Batalkan',f'p:cancel:{ident}')]]
            try: status=await self.service.check(ident,user,True)
            except ValueError:
                return await self.text(user,panel('🔎 Belum bisa dicek',
                    'Ada kendala koneksi sebentar. Coba cek lagi nanti, ya. Kalau sudah membayar, jangan bayar ulang 🤍'),controls)
            if status=='verified': return
            if status=='late':
                return await self.text(user,panel('Pembayaran tercatat','Pembayaran diterima setelah pembatalan. Pemilik telah diberi tahu.'),[HOME])
            return await self.text(user,panel('⏳ Menunggu pembayaranmu',
                'Kalau sudah membayar, tunggu sebentar, ya. Link aksesmu akan dikirim otomatis setelah terkonfirmasi 🤍'),controls)
        if data.startswith('p:cancel:'):
            ident=parts[2]
            self.store.cancel(self.bot,user,ident)
            await self.service.cleanup_qr(ident)
            if self.store.order(self.bot,ident,user)['payment']=='verified':
                return await self.text(user,'Pembayaran sudah berhasil; akses tersedia di Pembelian Saya.',[HOME])
            return await self.text(user,panel('🍃 Pesanan dibatalkan',
                'Mau lanjut? Pilih akses dan buat pesanan baru, ya.\n\nJangan membayar QRIS dari pesanan ini.'),[[button('🛍 Pilih Akses','p:list:0')]])
        if data.startswith('bc:stop:'):
            if not await self.broadcast.stop(user,parts[2]): raise PermissionError('Hanya pembuat broadcast yang boleh menghentikannya.')
            return
        self.staff(user)
        if data.startswith('bc:send:'):
            state=self.state(user)
            if not state or state['kind']!='broadcast_confirm' or state.get('nonce')!=parts[2]: raise ValueError('Konfirmasi broadcast sudah berakhir.')
            await self.broadcast.start(user,parts[2])
            self.clear(user)
            return
        if data=='p:broadcast':
            self.wait(user,'broadcast')
            return await self.text(user,panel('📢 Siapkan broadcast','Kirim pesan yang ingin disampaikan kepada seluruh pengguna bot ini.'),[[button('✖️ Batalkan','x:cancel')]])
        if data.startswith(('p:orders:','p:order:','p:sort:','p:sortitem:','p:move:','p:account','p:webhook','p:admins','p:add_admin','p:remove_admin','p:new','p:ask:','p:status:')): self.owner(user)
        if data.startswith('p:orders:'):
            page=max(0,int(parts[2]))
            rows=self.db.rows('SELECT id,name,buyer,payment FROM payment_orders WHERE bot=? ORDER BY created DESC LIMIT 9 OFFSET ?', (self.bot,page*8))
            buttons=[[button(r['name']+' · '+r['payment'],f'p:order:{r["id"]}')] for r in rows[:8]]
            moves=[]
            if page: moves.append(button('‹ Sebelumnya',f'p:orders:{page-1}'))
            if len(rows)>8: moves.append(button('Berikutnya ›',f'p:orders:{page+1}'))
            if moves: buttons.append(moves)
            buttons.append([button('‹ Pengaturan','p:settings')])
            return await self.text(user,panel('Transaksi bot 🧾','Status internal untuk pemilik. Pembayaran dan pengiriman akses dicatat terpisah.'),buttons)
        if data.startswith('p:order:'):
            order=self.store.order(self.bot,parts[2])
            return await self.text(user,panel('Detail transaksi 🔎',
                f'Pesanan: {h(order["id"])}\nAkses: {h(order["name"])}\nPembeli: {order["buyer"]}\nHarga: Rp{order["price"]:,}\nTotal QRIS: {h(order["total"])}\nStatus pesanan: {h(order["state"])}\nPembayaran: {h(order["payment"])}\nPengiriman: {h(order["delivery"])}\nLink digunakan: {bool(order["used"])}'),
                [[button('‹ Transaksi','p:orders:0')]])
        if data=='p:welcome_menu':
            return await self.text(user,panel('Sambutan ✨','Pilih bagian sambutan yang ingin diubah.'),
                [[button('✏️ Teks Sambutan','p:welcome'),button('🖼 Foto Sambutan','p:welcome_photo')],[button('‹ Pengaturan','p:settings')]])
        if data=='p:save_welcome':
            state=self.state(user)
            if not state or state['kind']!='welcome_confirm': raise ValueError('Preview sudah berakhir.')
            self.db.setting(self.bot,user,state['field'],state['value'])
            self.clear(user)
            return await self.text(user,panel('✅ Beres, sudah disimpan!','Perubahanmu sudah diterapkan ✨'),[[button('⚙️ Pengaturan','p:settings')]])
        if data.startswith('p:sort:'):
            rows=self.store.packages(self.bot,True)
            page=max(0,int(parts[2]))
            buttons=[[button(row['name'],f'p:sortitem:{row["id"]}')] for row in rows[page*8:(page+1)*8]]
            moves=[]
            if page: moves.append(button('‹ Sebelumnya',f'p:sort:{page-1}'))
            if len(rows)>(page+1)*8: moves.append(button('Berikutnya ›',f'p:sort:{page+1}'))
            if moves: buttons.append(moves)
            return await self.text(user,panel('Urutan Akses','Pilih nama akses untuk mengubah posisinya.'),buttons+[[button('‹ Pengaturan','p:settings')]])
        if data.startswith('p:move:'):
            self.store.move(self.bot,user,int(parts[2]),int(parts[3]))
            return await self.callback(user,'p:sortitem:'+parts[2],message)
        if data.startswith('p:sortitem:'):
            p=self.store.package(self.bot,int(parts[2]))
            return await self.text(user,panel('Urutan Akses',h(p['name'])),
                [[button('⬆️ Naik',f'p:move:{p["id"]}:-1'),button('⬇️ Turun',f'p:move:{p["id"]}:1')],[button('‹ Daftar Akses','p:sort:0')]])
        if data=='p:admins':
            rows=self.db.admins(self.bot)
            body='Admin dapat mengedit tampilan akses, sambutan, dan mengirim broadcast.'
            if rows: body+='\n\n'+', '.join(str(item) for item in rows)
            return await self.text(user,panel('Admin 👤',body),[[button('＋ Tambah Admin','p:add_admin'),button('Cabut Admin','p:remove_admin')],[button('‹ Pengaturan','p:settings')]])
        if data in ('p:add_admin','p:remove_admin'):
            self.wait(user,'add_admin' if data=='p:add_admin' else 'remove_admin')
            return await self.text(user,'Kirim ID Telegram pengguna. Admin baru harus membuka bot dan menekan Start sekali sebelum ditambahkan.',[[button('✖️ Batalkan','x:cancel')]])
        if data.startswith('p:remove_admin_yes:'):
            state=self.state(user); target=int(parts[2])
            if not state or state['kind']!='remove_admin_confirm' or state['target']!=target: raise ValueError('Konfirmasi sudah berakhir.')
            self.db.admin(self.bot,user,target,False)
            try: await self.durable(target,panel('🔒 Akses admin berakhir','Kamu tetap bisa membeli dan menggunakan akses seperti biasa 🤍'))
            except TelegramFailure: pass
            self.clear(user)
            return await self.text(user,panel('✅ Perubahan tersimpan','Akses admin sudah dicabut.'),[[button('‹ Admin','p:admins')]])
        if data=='p:settings': return await self.settings(user)
        if data.startswith('p:manage:'): return await self.listing(user,int(parts[2]),True)
        if data=='p:new':
            self.wait(user,'new_package',step='name',values={})
            return await self.text(user,'Kirim nama akses (maksimal 80 karakter).',[[button('✖️ Batal','x:cancel')]])
        if data.startswith('p:edit:'):
            ident=int(parts[2]); self.store.package(self.bot,ident)
            field=parts[3]
            if user!=self.db.bot(self.bot)['owner'] and field not in ('name','description','photo'): raise PermissionError('Bagian ini hanya untuk owner.')
            if field not in ('name','description','price','target','photo'): raise ValueError('Field tidak dikenal.')
            self.wait(user,'edit_package',ident=ident,field=field)
            return await self.text(user,'Kirim '+('foto sebagai foto, atau ketik hapus untuk menghapus foto.' if field=='photo' else field+' baru.'),[[button('✖️ Batal','x:cancel')]])
        if data.startswith('p:ask:'):
            ident=int(parts[2]); status=parts[3]; self.store.package(self.bot,ident)
            self.wait(user,'package_status',ident=ident,status=status)
            return await self.text(user,panel('Konfirmasi perubahan 🔎','Nonaktifkan/hapus akses akan membatalkan semua pesanan yang belum dibayar. Pembelian berhasil tetap disimpan.'),[[button('Ya, lanjutkan',f'p:status:{ident}:{status}'),button('Batal','x:cancel')]])
        if data.startswith('p:status:'):
            state=self.state(user)
            if not state or state['kind']!='package_status' or state['ident']!=int(parts[2]) or state['status']!=parts[3]: raise ValueError('Konfirmasi berakhir.')
            self.store.package_status(self.bot,user,state['ident'],state['status'])
            return await self.listing(user,0,True)
        if data=='p:account':
            self.wait(user,'account',step='username')
            return await self.text(user,panel('Hubungkan Saweria 💳','Kirim username Saweria milikmu. Pengaturan ini dipakai bersama oleh bot Payment lain milikmu.'),[[button('✖️ Batal','x:cancel')]])
        if data=='p:webhook':
            account=self.store.account(user)
            if not account or not self.public_base: raise ValueError('Hubungkan akun dan siapkan URL webhook HTTPS di server terlebih dahulu.')
            url=self.public_base+'/saweria/'+account['route']
            return await self.text(user,panel('Webhook Saweria 🔗',
                'Tempel URL privat ini di HTTP Webhook Saweria dan aktifkan. Jangan bagikan URL ini.\n\n'+h(url)+'\n\nSatu URL untuk semua bot Payment milikmu. Kunci streaming harus sesuai dengan akun Saweria ini.'),[[link_button('Buka dokumentasi Saweria','https://saweria.co/docs/webhook')],[button('‹ Pengaturan','p:settings')]])
        if data in ('p:welcome','p:welcome_photo'):
            self.wait(user,'welcome',photo=data.endswith('_photo'))
            return await self.text(user,'Kirim foto sambutan (atau hapus) sekarang.' if data.endswith('_photo') else 'Kirim teks sambutan, maksimal 1000 karakter.',[[button('✖️ Batal','x:cancel')]])

    async def message(self,user,message):
        cmd,_=command(message)
        if cmd=='/start':
            self.store.mark_started(self.bot,user)
            return await self.home(user)
        if cmd=='/help': return await self.home(user)
        if cmd=='/broadcast':
            return await self.callback(user,'p:broadcast',message)
        if cmd in ('/setting','/settings'): return await self.settings(user)
        state=self.state(user)
        if not state: return await self.home(user)
        text=message.get('text','').strip()
        self.staff(user)
        if state['kind'] in ('account','new_package','add_admin','remove_admin'): self.owner(user)
        if state['kind']=='broadcast':
            nonce=await self.broadcast.preview(user,message['message_id'])
            self.wait(user,'broadcast_confirm',nonce=nonce)
            return
        if state['kind']=='add_admin':
            target=self.positive_id(text)
            if target==self.db.bot(self.bot)['owner']: raise ValueError('Owner sudah memiliki akses penuh.')
            if not self.store.started(self.bot,target):
                return await self.text(user,panel('👋 Admin belum bisa ditambahkan',
                    'Minta dia membuka bot dan menekan /start dulu, lalu tambahkan kembali, ya.\n\nIzin admin belum diberikan.'),[[button('‹ Admin','p:admins')]])
            try:
                await self.durable(target,panel('✨ Kamu sekarang admin','Kamu bisa mengatur tampilan akses, sambutan, dan mengirim broadcast.\n\nBuka /setting untuk mulai 🤍'))
            except TelegramFailure:
                return await self.text(user,panel('👋 Admin belum bisa ditambahkan',
                    'Minta dia membuka bot dan menekan /start dulu, lalu tambahkan kembali, ya.\n\nIzin admin belum diberikan.'),[[button('‹ Admin','p:admins')]])
            self.db.admin(self.bot,user,target,True)
            self.clear(user)
            return await self.text(user,panel('✅ Perubahan tersimpan','Admin berhasil ditambahkan.'),[[button('‹ Admin','p:admins')]])
        if state['kind']=='remove_admin':
            target=self.positive_id(text)
            if target not in self.db.admins(self.bot): raise ValueError('Pengguna tidak terdaftar sebagai admin.')
            self.wait(user,'remove_admin_confirm',target=target)
            return await self.text(user,panel('Cabut akses admin?','Pengguna tersebut tetap dapat menggunakan bot sebagai pembeli.'),
                [[button('Cabut Admin',f'p:remove_admin_yes:{target}'),button('Batal','x:cancel')]])
        if state['kind']=='account':
            username=text.lower()
            recipient=await self.provider.recipient(username)
            self.store.account(user,username,recipient,enabled=True)
            self.clear(user)
            return await self.text(user,panel('Saweria terhubung ✅',
                'Akun: <b>'+h(username)+'</b>\nPembayaran akan diperiksa otomatis. Tidak perlu stream key atau webhook.\nPastikan username ini milikmu dan periksa penerima saat uji pembayaran.'),
                [[button('‹ Pengaturan','p:settings')]])
        if state['kind']=='welcome':
            field='payment_photo' if state['photo'] else 'payment_welcome'
            if state['photo']:
                photos=message.get('photo',[])
                value=photos[-1]['file_id'] if photos else (None if text.lower()=='hapus' else False)
                if value is False: raise ValueError('Kirim foto atau ketik hapus.')
            else:
                value=text
                if not value or len(value)>1000: raise ValueError('Teks harus 1–1000 karakter.')
            self.wait(user,'welcome_confirm',field=field,value=value)
            settings=self.db.settings(self.bot)|{field:value}
            body=settings['payment_welcome'].replace('{nama_pengguna}',self.names.get(user,'teman')).replace('{nama_bot}',self.db.bot(self.bot).get('name') or 'botmu')
            return await self.photo_text(user,settings['payment_photo'],panel('👁 Preview Sambutan',h(body)),
                [[button('✅ Simpan','p:save_welcome'),button('✖️ Batalkan','x:cancel')]])
        if state['kind']=='edit_package':
            field=state['field']
            value=await self.package_value(field,text,message)
            self.store.save_package(self.bot,user,state['ident'],**{field:value})
            self.clear(user)
            return await self.text(user,panel('✅ Beres, sudah disimpan!','Perubahanmu sudah diterapkan ✨'),[[button('‹ Kembali',f'p:package:{state["ident"]}:1')]])
        if state['kind']=='new_package':
            field=state['step']
            state['values'][field]=await self.package_value(field,text,message)
            fields=('name','description','price','target')
            index=fields.index(field)+1
            if index<len(fields):
                state['step']=fields[index]
                prompts={'description':'Kirim deskripsi akses (maksimal 1000 karakter).','price':'Kirim harga akses dalam rupiah, tanpa titik.','target':'Kirim ID channel/grup privat (ID negatif). Bot harus admin dengan izin undangan.'}
                return await self.text(user,prompts[state['step']],[[button('✖️ Batal','x:cancel')]])
            ident=self.store.save_package(self.bot,user,**state['values'])
            return await self.package(user,ident,True)

    async def package_value(self,field,text,message):
        if field=='photo':
            photos=message.get('photo',[])
            if photos: return photos[-1]['file_id']
            if text.lower()=='hapus': return None
            raise ValueError('Kirim foto sebagai foto.')
        if field in ('price','target'):
            try: value=int(text)
            except ValueError: raise ValueError('Masukkan angka tanpa titik.') from None
            if field=='target': await self.service.target(value)
            elif value<1000: raise MinimumPriceError('Harga minimal Rp1.000')
            elif value>100_000_000: raise ValueError('Harga harus positif dan maksimal Rp100 juta.')
            return value
        if not text or len(text)>(80 if field=='name' else 1000): raise ValueError('Teks terlalu panjang/kosong.')
        return text
