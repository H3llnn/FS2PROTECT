"""Child settings, content links, ordered batches and owner broadcasts."""
import asyncio
import secrets
import time
from .ui_base import BaseUI, command, FILES
from .copy import h, panel, pretty, button, copy_button, minutes, nav, DENIED_UPLOAD
from .service import Delivery, TelegramFailure

SETTINGS = [[button('⚙️ Pengaturan', 's:menu')]]
BATCH_BUTTONS = [[button('✓ Selesai', 'b:done'), button('✕ Batal', 'x:cancel')]]
PROMPTS = {
 'database': ('Pilih ruang penyimpananmu 🗂️', 'Kirim <b>ID channel database</b> yang ingin digunakan.\nPastikan bot sudah menjadi admin dengan izin mengirim dan menghapus pesan, ya.'),
 'add_target': ('Atur gerbang aksesmu 🔐', 'Kirim <b>ID channel atau grup</b> yang wajib diikuti pengguna.\nPastikan bot sudah menjadi admin dengan izin mengundang pengguna, ya.'),
 'add_admin': ('Tambah pengelola konten 👤', 'Kirim <b>ID Telegram pengguna</b> yang ingin dijadikan admin.\nAdmin hanya bisa membuat link satu konten dan batch.'),
 'remove_admin': ('Hapus akses admin 🔐', 'Kirim <b>ID Telegram admin</b> yang ingin dihapus.'),
 'welcome': ('Sambut pengguna dengan gayamu ✨', 'Kirim teks yang ingin ditampilkan saat pengguna membuka bot.\nMaksimal <b>1.000 karakter</b>, ya.'),
 'welcome_photo': ('Beri sentuhan pada botmu 🖼️', 'Kirim foto yang ingin ditampilkan bersama pesan sambutan.\nKirim sebagai <b>foto</b>, bukan dokumen, ya.'),
 'force_message': ('Atur pesan gerbangmu 🔐', 'Kirim teks yang ditampilkan saat pengguna belum mengikuti semua ForceSubs.\nMaksimal <b>1.000 karakter</b>, ya.\n\nTombol join dan <b>Coba Lagi</b> akan ditambahkan otomatis.'),
 'delete_seconds': ('Atur waktu kontenmu ⏳', 'Masukkan durasi dalam menit: <b>1–2.879</b>.'),
 'delete_notice': ('Atur pengingat waktumu ⏳', 'Kirim pesan yang akan ditampilkan setelah konten terkirim.\nGunakan <b>{durasi}</b> agar waktu penghapusan terisi otomatis.\n\nMaksimal <b>1.000 karakter</b>, ya.'),
}


class ChildUI(BaseUI):
    def __init__(self, db, bot, api):
        super().__init__(db, api)
        self.bot = bot
        self.delivery = Delivery(db, bot, api)
        self.broadcasting = False

    def expiry_buttons(self, state):
        return [[button('↻ Mulai Lagi', state.get('back', 's:home')), button('⌂ Menu Utama', 's:home')]]

    async def cancelled(self, user):
        self.clear(user)
        await self.text(user, panel('Dibatalkan 🍃', 'Prosesnya sudah dihentikan.\nKamu bisa mulai lagi kapan saja.'),
                        [[button('⌂ Menu Utama', 's:home')]])

    async def name(self):
        row = self.db.bot(self.bot)
        try:
            me = await self.api.call('getMe')
            if isinstance(me, dict):
                name = ' '.join(v for v in (me.get('first_name'), me.get('last_name')) if v)
                if name:
                    self.db.display_name(self.bot, name)
                    return name
        except TelegramFailure:
            pass
        return row.get('name') or 'botmu'

    async def welcome(self, user):
        s = self.db.settings(self.bot)
        text = s['welcome'].replace('{nama_bot}', await self.name()).replace('{nama_pengguna}', self.names.get(user, 'teman'))
        buttons = SETTINGS if user == self.db.bot(self.bot)['owner'] else []
        await self.photo_text(user, (s['welcome_photo'] or {}).get('file_id'), pretty(text), buttons)

    async def settings_menu(self, user):
        self.db.owner(self.bot, user)
        self.clear(user)
        s = self.db.settings(self.bot)
        database = str(s['database'] or 'Belum diatur')
        if s['database']:
            try:
                info = await self.api.call('getChat', chat_id=s['database'])
                if isinstance(info, dict):
                    database = info.get('title', database)
            except TelegramFailure:
                pass
        buttons = [
          [button('🗂️ Channel Database', 's:database'), button('🔐 ForceSubs', 's:targets')],
          [button('👤 Admin Pembuat Link', 's:admins')],
          [button('✏️ Teks Sambutan', 's:welcome'), button('🖼️ Foto Sambutan', 's:welcome_photo')],
          [button('🗑️ Hapus Foto Sambutan', 's:clear_photo')],
          [button('🔐 Pesan Wajib Join', 's:force_message')],
          [button('🔐 Proteksi Konten', 's:protection')],
          [button('⏳ Hapus Otomatis', 's:deletion'), button('✏️ Pesan Penghapusan', 's:delete_notice')],
          [button('📣 Broadcast', 's:broadcast')]]
        await self.text(user, panel('Atur botmu ⚙️',
          f'<b>Bot:</b> @{h(self.db.bot(self.bot)["username"])}\n<b>Database:</b> {h(database)}\n'
          f'<b>ForceSubs:</b> {len(self.db.targets(self.bot))}/4\n'
          f'<b>Proteksi konten:</b> {"Aktif" if s["protection"] else "Nonaktif"}\n'
          f'<b>Hapus otomatis:</b> {minutes(s["delete_seconds"])}\n\nPilih bagian yang ingin kamu ubah.'), buttons)

    async def targets_menu(self, user):
        self.db.owner(self.bot, user)
        self.clear(user)
        targets = self.db.targets(self.bot)
        buttons = [[button('＋ Tambah Channel/Group', 's:add_target')]] if len(targets) < 4 else []
        buttons += [[button('🗑️ '+(t.get('title') or str(t['chat'])), f's:remove_target:{t["chat"]}')] for t in targets]
        await self.text(user, panel('Daftar gerbang akses 🔐',
          f'Slot terpakai: <b>{len(targets)}/4</b>.\nSemua channel/grup dalam daftar wajib diikuti.'), buttons+SETTINGS)

    async def admins_menu(self, user, page=0):
        self.db.owner(self.bot, user)
        self.clear(user)
        admins = self.db.admins(self.bot)
        page = max(0, min(page, max(0, (len(admins)-1)//20)))
        listed = ', '.join(str(a) for a in admins[page*20:(page+1)*20]) or 'Belum ada admin tambahan.'
        buttons = [[button('＋ Tambah ID Admin', 's:add_admin'), button('🗑️ Hapus ID Admin', 's:remove_admin')]]
        pages = []
        if page:
            pages.append(button('‹ Sebelumnya', f's:admins:{page-1}'))
        if (page+1)*20 < len(admins):
            pages.append(button('Berikutnya ›', f's:admins:{page+1}'))
        if pages:
            buttons.append(pages)
        await self.text(user, panel('Pengelola kontenmu 👤', listed+'\n\nAdmin hanya dapat membuat link.'), buttons+SETTINGS)

    async def prompt(self, user, key):
        self.db.owner(self.bot, user)
        back = ('s:targets' if key == 'add_target' else 's:admins' if key in ('add_admin', 'remove_admin')
                else 's:deletion' if key == 'delete_seconds' else 's:menu')
        if key == 'add_target' and len(self.db.targets(self.bot)) >= 4:
            self.clear(user)
            return await self.text(user, panel('Semua slot sudah terisi 🔐',
              'Botmu sudah memakai <b>4 dari 4 slot ForceSubs</b>.\nHapus salah satu channel atau grup jika ingin menggantinya.'),
              [[button('‹ Daftar ForceSubs', 's:targets')]])
        self.wait(user, 'setting', key=key, back=back)
        title, body = PROMPTS[key]
        if key == 'add_target':
            body += f'\n\nTersedia <b>{4-len(self.db.targets(self.bot))} dari 4 slot</b>.'
        buttons = [[button('👁️ Lihat Pesan Saat Ini', f's:view:{key}')]] if key in ('welcome', 'force_message', 'delete_notice') else []
        await self.text(user, panel(title, body), buttons+nav('s:back'))

    async def protection_menu(self, user):
        self.db.owner(self.bot, user)
        self.clear(user)
        active = self.db.settings(self.bot)['protection']
        await self.text(user, panel('Atur perlindungan kontenmu 🔐',
          f'Status: <b>{"Aktif" if active else "Nonaktif"}</b>\n\n'
          'Aktifkan untuk membatasi penyimpanan dan penerusan konten melalui fitur Telegram.'),
          [[button('🔓 Nonaktifkan' if active else '🔐 Aktifkan', f's:protect:{0 if active else 1}')],
           [button('‹ Kembali', 's:menu')]])

    async def deletion_menu(self, user):
        self.db.owner(self.bot, user)
        self.clear(user)
        await self.text(user, panel('Atur waktu kontenmu ⏳',
          f'Durasi saat ini: <b>{minutes(self.db.settings(self.bot)["delete_seconds"])}</b>\n\n'
          'Pilih durasi atau masukkan waktu sendiri dalam menit.'),
          [[button('15 Menit', 's:duration:15'), button('30 Menit', 's:duration:30')],
           [button('1 Jam', 's:duration:60'), button('24 Jam', 's:duration:1440')],
           [button('✏️ Durasi Lain', 's:delete_seconds'), button('Nonaktifkan', 's:duration:0')],
           [button('‹ Kembali', 's:menu')]])

    async def duration_saved(self, user, count):
        self.db.setting(self.bot, user, 'delete_seconds', count*60)
        self.clear(user)
        text = (panel('Waktunya sudah diatur ⏳',
          f'Konten yang dikirim berikutnya akan dihapus otomatis setelah <b>{minutes(count*60)}</b>.')
          if count else panel('Hapus otomatis dinonaktifkan ✅', 'Konten yang dikirim berikutnya akan tetap berada di chat pengguna.'))
        await self.text(user, text, [[button('‹ Hapus Otomatis', 's:deletion')], *SETTINGS])

    async def begin_broadcast(self, user):
        self.db.owner(self.bot, user)
        if self.broadcasting:
            raise ValueError('Broadcast sebelumnya masih berlangsung.')
        self.wait(user, 'broadcast', back='s:broadcast')
        await self.text(user, panel('Siapkan broadcastmu 📣',
          'Kirim pesan yang ingin kamu sampaikan ke seluruh pengguna bot ini.\nBisa berupa teks, foto, video, atau file.'),
          [[button('✕ Batal', 'x:cancel')]])

    async def confirm_broadcast(self, user, message_id):
        self.db.owner(self.bot, user)
        if self.broadcasting:
            raise ValueError('Broadcast sebelumnya masih berlangsung.')
        nonce = secrets.token_hex(4)
        self.wait(user, 'broadcast_confirm', message=message_id, nonce=nonce, back='s:broadcast')
        await self.text(user, panel('Siap dikirim? 📣',
          f'Pesan ini akan dikirim ke <b>{len(self.db.users(self.bot))} pengguna</b> botmu.\nPastikan isinya sudah sesuai, ya.'),
          [[button('📣 Kirim Sekarang', f's:send_broadcast:{nonce}'), button('✕ Batal', 'x:cancel')]])

    async def callback(self, user, data, message):
        if data == 'x:cancel':
            return await self.cancelled(user)
        if data == 's:home':
            self.clear(user)
            return await self.welcome(user)
        if data.startswith('get:'):
            return await self.delivery.deliver(user, data[4:])
        if data == 'b:done':
            return await self.finish_batch(user)
        if data == 'b:start':
            return await self.begin_batch(user)
        self.db.owner(self.bot, user)
        if data == 's:back':
            state = self.state(user)
            back = state.get('back', 's:menu') if state else 's:menu'
            self.clear(user)
            return await self.callback(user, back, message)
        if data == 's:menu':
            return await self.settings_menu(user)
        if data == 's:targets':
            return await self.targets_menu(user)
        if data == 's:admins' or data.startswith('s:admins:'):
            return await self.admins_menu(user, int(data.split(':')[2]) if data.count(':') == 2 else 0)
        if data.startswith('s:remove_target:'):
            chat = int(data.split(':')[2])
            target = next((t for t in self.db.targets(self.bot) if t['chat'] == chat), None)
            if not target:
                return await self.targets_menu(user)
            self.wait(user, 'remove_target', chat=chat, back='s:targets')
            return await self.text(user, panel('Hapus dari ForceSubs? 🗑️',
              f'<b>{h(target.get("title") or chat)}</b> tidak lagi wajib diikuti pengguna setelah dihapus.'),
              [[button('🗑️ Hapus', f's:remove_target_yes:{chat}'), button('‹ Kembali', 's:targets')]])
        if data.startswith('s:remove_target_yes:'):
            chat = int(data.split(':')[2])
            state = self.state(user)
            if not state or state['kind'] != 'remove_target' or state['chat'] != chat:
                raise ValueError('Konfirmasi sudah berakhir. Pilih channel/grup kembali.')
            target = next((t for t in self.db.targets(self.bot) if t['chat'] == chat), {})
            self.db.remove_target(self.bot, user, chat)
            self.clear(user)
            return await self.text(user, panel('Daftar akses diperbarui ✨',
              f'<b>{h(target.get("title") or chat)}</b> sudah dihapus dari ForceSubs.\nSlot terpakai: <b>{len(self.db.targets(self.bot))}/4</b>.'),
              [[button('‹ Daftar ForceSubs', 's:targets')], *SETTINGS])
        if data.startswith('s:remove_admin_yes:'):
            target = int(data.split(':')[2])
            state = self.state(user)
            if not state or state['kind'] != 'remove_admin' or state['target'] != target:
                raise ValueError('Konfirmasi sudah berakhir. Pilih admin kembali.')
            self.db.admin(self.bot, user, target, False)
            self.clear(user)
            return await self.text(user, panel('Akses admin diperbarui ✅',
              f'Pengguna dengan ID <b>{target}</b> tidak lagi bisa membuat link di botmu.'),
              [[button('‹ Daftar Admin', 's:admins')], *SETTINGS])
        if data == 's:protection':
            return await self.protection_menu(user)
        if data.startswith('s:protect:'):
            value = data.split(':')[2]
            if value not in ('0', '1'):
                raise ValueError('Pilihan proteksi tidak valid.')
            self.db.setting(self.bot, user, 'protection', value == '1')
            return await self.protection_menu(user)
        if data == 's:deletion':
            return await self.deletion_menu(user)
        if data == 's:no_delete':
            return await self.duration_saved(user, 0)
        if data.startswith('s:duration:'):
            return await self.duration_saved(user, int(data.split(':')[2]))
        if data == 's:clear_photo':
            self.db.setting(self.bot, user, 'welcome_photo', None)
            self.clear(user)
            return await self.text(user, panel('Foto sambutan dihapus ✅', 'Pesan sambutan kini ditampilkan tanpa foto.'), SETTINGS)
        if data == 's:preview':
            return await self.welcome(user)
        if data.startswith('s:view:'):
            key = data.split(':')[2]
            if key not in ('welcome', 'force_message', 'delete_notice'):
                raise ValueError('Pesan tidak ditemukan.')
            return await self.text(user, pretty(self.db.settings(self.bot)[key]), [[button('‹ Kembali', f's:{key}')]])
        if data == 's:broadcast':
            return await self.begin_broadcast(user)
        if data.startswith('s:send_broadcast:'):
            state = self.state(user)
            if not state or state['kind'] != 'broadcast_confirm' or state['nonce'] != data.split(':')[2]:
                raise ValueError('Konfirmasi broadcast sudah berakhir. Siapkan pesan lagi.')
            self.clear(user)
            return await self.broadcast(user, state['message'])
        if data == 's:retry':
            state = self.state(user)
            if not state or state['kind'] != 'setting' or 'retry_message' not in state:
                raise ValueError('Sesi sudah berakhir. Buka pengaturan kembali.')
            return await self.apply_setting(user, state['retry_message'], state['key'])
        key = data.removeprefix('s:')
        if key in PROMPTS:
            return await self.prompt(user, key)

    async def begin_batch(self, user):
        if not self.db.can_upload(self.bot, user):
            return await self.text(user, DENIED_UPLOAD)
        self.wait(user, 'batch', sources=[], back='b:start')
        await self.text(user, panel('Susun kontenmu 📦',
          'Kirim teks, foto, video, atau file sesuai urutan yang kamu inginkan.\nKalau sudah lengkap, tekan <b>Selesai</b>.'), BATCH_BUTTONS)

    async def message(self, user, message):
        self.db.add_user(self.bot, user)
        cmd, arg = command(message)
        if cmd in ('/setting', '/settings'):
            return await self.settings_menu(user)
        if cmd == '/start':
            self.clear(user)
            return await self.delivery.deliver(user, arg) if arg else await self.welcome(user)
        if cmd == '/help':
            return await self.text(user, panel('Panduan singkat ✨',
              'Buka link konten untuk mengambil isinya.\nPemilik/admin: kirim teks atau file, atau gunakan /batch.\nPemilik: /setting dan /broadcast.'))
        if cmd == '/broadcast':
            self.db.owner(self.bot, user)
            if message.get('reply_to_message'):
                return await self.confirm_broadcast(user, message['reply_to_message']['message_id'])
            return await self.begin_broadcast(user)
        if cmd == '/batch':
            return await self.begin_batch(user)
        if cmd.startswith('/'):
            return
        state = self.state(user)
        if state and state['kind'] == 'setting':
            return await self.apply_setting(user, message, state['key'])
        if state and state['kind'] == 'broadcast':
            return await self.confirm_broadcast(user, message['message_id'])
        if state and state['kind'] != 'batch':
            return await self.text(user, panel('Tentukan pilihanmu dulu ✨',
              'Gunakan tombol pada pesan sebelumnya, atau batalkan prosesnya.'), [[button('✕ Batal', 'x:cancel')]])
        if not (message.get('text', '').strip() or any(k in message for k in FILES) or message.get('forward_origin')):
            return
        if not self.db.can_upload(self.bot, user):
            return await self.text(user, DENIED_UPLOAD)
        source = self.db.settings(self.bot)['database']
        if not source:
            return await self.text(user, panel('Penyimpanan belum siap 🗂️',
              'Pemilik perlu mengatur channel database melalui pengaturan terlebih dahulu.'),
              SETTINGS if user == self.db.bot(self.bot)['owner'] else None)
        await self.delivery.validate_chat(source, database=True)
        saved = await self.api.call('copyMessage', chat_id=source, from_chat_id=user, message_id=message['message_id'])
        metadata = None
        if message.get('photo'):
            metadata = {'type': 'photo', 'media': message['photo'][-1]['file_id']}
        elif message.get('video'):
            metadata = {'type': 'video', 'media': message['video']['file_id']}
        if metadata:
            for key in ('caption', 'caption_entities'):
                if key in message:
                    metadata[key] = message[key]
            if message.get('has_media_spoiler'):
                metadata['has_spoiler'] = True
            self.db.content(self.bot, source, saved['message_id'], metadata)
        pair = (source, saved['message_id'])
        if state and state['kind'] == 'batch':
            state['sources'].append(pair)
            state['expires'] = time.monotonic()+600
            return await self.text(user, panel(f'{len(state["sources"])} konten tersimpan 📦',
              'Masih ada yang mau ditambahkan?\nKirim konten berikutnya, atau tekan <b>Selesai</b> kalau sudah lengkap.'), BATCH_BUTTONS)
        return await self.share(user, [pair])

    async def apply_setting(self, user, message, key):
        self.db.owner(self.bot, user)
        state = self.state(user)
        try:
            result = await self.save_setting(user, message, key)
        except (TelegramFailure, ValueError) as exc:
            permission_error = isinstance(exc, TelegramFailure) or any(t in str(exc).lower() for t in ('izin', 'admin'))
            if key in ('database', 'add_target') and permission_error:
                state['retry_message'] = message
                required = ('Mengirim dan menghapus pesan di channel database.' if key == 'database'
                            else 'Status admin dan izin mengundang pengguna di channel/grup.')
                return await self.text(user, panel('Izinnya belum lengkap 🔧',
                  'Pengaturan belum disimpan.\nTambahkan bot sebagai admin di channel atau grup tersebut, lalu lengkapi izin berikut:\n\n'
                  f'<b>{required}</b>'), [[button('↻ Coba Lagi', 's:retry'), button('‹ Kembali', 's:back')]])
            raise
        if key == 'remove_admin':
            return
        self.clear(user)
        if key == 'database':
            return await self.text(user, panel('Penyimpananmu siap 🗂️',
              'Channel database berhasil diatur.\nKonten baru akan disimpan di sini.'), SETTINGS)
        if key == 'add_target':
            count = len(self.db.targets(self.bot))
            buttons = [[button('＋ Tambah Lagi', 's:add_target')]] if count < 4 else []
            buttons.append([button('‹ Daftar ForceSubs', 's:targets')])
            return await self.text(user, panel('Gerbang akses ditambahkan 🔐',
              f'<b>{h(result.get("title") or result["chat"])}</b> berhasil masuk ke daftar ForceSubs.\n'
              f'Pengguna wajib bergabung sebelum mengambil konten.\n\nSlot terpakai: <b>{count}/4</b>.'), buttons)
        if key == 'add_admin':
            return await self.text(user, panel('Admin berhasil ditambahkan ✅',
              f'Pengguna dengan ID <b>{result}</b> sekarang bisa membuat link di botmu.'),
              [[button('‹ Daftar Admin', 's:admins')], *SETTINGS])
        if key == 'delete_seconds':
            return await self.duration_saved(user, result)
        messages = {
          'welcome': ('Sambutanmu diperbarui ✅', 'Teks baru siap menyambut pengguna botmu.'),
          'welcome_photo': ('Tampilan barumu siap ✨', 'Foto sambutan berhasil diperbarui.'),
          'force_message': ('Pesan akses diperbarui ✅', 'Pesan wajib join yang baru sudah tersimpan.'),
          'delete_notice': ('Pengingatmu diperbarui ✅', 'Pesan penghapusan yang baru sudah tersimpan.')}
        buttons = ([[button('👁️ Preview Sambutan', 's:preview')]] if key.startswith('welcome') else [])+SETTINGS
        await self.text(user, panel(*messages[key]), buttons)

    async def save_setting(self, user, message, key):
        text = message.get('text', '').strip()
        if key in ('database', 'add_target'):
            try:
                chat = int(text)
            except ValueError:
                raise ValueError('ID channel/grup harus berupa angka negatif, misalnya -1001234567890.') from None
            if key == 'database':
                await self.delivery.validate_chat(chat, database=True)
                self.db.setting(self.bot, user, key, chat)
            else:
                if len(self.db.targets(self.bot)) >= 4 and chat not in [t['chat'] for t in self.db.targets(self.bot)]:
                    raise ValueError('Semua slot sudah terisi. Hapus salah satu ForceSubs terlebih dahulu.')
                result = await self.delivery.validate_chat(chat)
                self.db.target(self.bot, user, **result)
                return result
        elif key in ('add_admin', 'remove_admin'):
            target = self.positive_id(text)
            if key == 'add_admin':
                self.db.admin(self.bot, user, target, True)
                return target
            if target not in self.db.admins(self.bot):
                raise ValueError('ID tersebut tidak terdaftar sebagai admin tambahan.')
            self.wait(user, 'remove_admin', target=target, back='s:admins')
            await self.text(user, panel('Hapus akses admin? 🔐',
              f'Pengguna dengan ID <b>{target}</b> tidak lagi bisa membuat link di botmu.\nLink yang sudah dibuat tetap tersedia.'),
              [[button('🗑️ Hapus Admin', f's:remove_admin_yes:{target}'), button('‹ Kembali', 's:admins')]])
        elif key == 'welcome_photo':
            if not message.get('photo'):
                raise ValueError('Kirim foto, bukan dokumen atau teks.')
            self.db.setting(self.bot, user, key, {'file_id': message['photo'][-1]['file_id']})
        elif key == 'delete_seconds':
            try:
                count = int(text)
                if not 0 <= count <= 2879:
                    raise ValueError
            except ValueError:
                raise ValueError('Durasi harus antara 1–2.879 menit. Pilih Nonaktifkan untuk mematikan penghapusan.') from None
            self.db.setting(self.bot, user, key, count*60)
            return count
        else:
            self.db.setting(self.bot, user, key, text)

    async def finish_batch(self, user):
        if not self.db.can_upload(self.bot, user):
            raise PermissionError('Pembuatan link hanya tersedia untuk pemilik dan admin bot ini.')
        state = self.state(user)
        if not state or state['kind'] != 'batch':
            return await self.text(user, panel('Paketmu masih kosong 📦',
              'Mulai batch baru, lalu kirim minimal satu konten, ya.'), [[button('＋ Mulai Batch', 'b:start')]])
        if not state['sources']:
            return await self.text(user, panel('Paketmu masih kosong 📦',
              'Kirim minimal satu konten dulu, ya.\nSetelah itu, tekan <b>Selesai</b>.'), BATCH_BUTTONS)
        await self.share(user, state['sources'], batch=True)
        self.clear(user)

    async def share(self, user, sources, batch=False):
        key = self.db.link(self.bot, user, sources)
        link = f'https://t.me/{self.db.bot(self.bot)["username"]}?start={key}'
        title = 'Paketmu siap dibagikan 🔗' if batch else 'Kontenmu siap dibagikan 🔗'
        body = f'<b>{len(sources)} konten</b> berhasil disatukan dalam satu link.' if batch else 'Link berhasil dibuat.'
        await self.durable(user, panel(title, body+'\n\n'+h(link)), [[copy_button(link)]])

    async def broadcast(self, user, message_id):
        self.db.owner(self.bot, user)
        if self.broadcasting:
            raise ValueError('Broadcast sebelumnya masih berlangsung.')
        self.broadcasting = True
        success = failed = 0
        try:
            await self.text(user, panel('Broadcast sedang dikirim… 📡',
              'Pesan sedang disampaikan ke pengguna botmu.\nTunggu sampai prosesnya selesai, ya.'))
            for target in self.db.users(self.bot):
                try:
                    await self.api.call('copyMessage', chat_id=target, from_chat_id=user, message_id=message_id)
                    success += 1
                except TelegramFailure:
                    failed += 1
                await asyncio.sleep(0.05)
            await self.durable(user, panel('Broadcast selesai ✨', f'✅ Berhasil: <b>{success}</b>\n⚠️ Gagal: <b>{failed}</b>'))
        finally:
            self.broadcasting = False
