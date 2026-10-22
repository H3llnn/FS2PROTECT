"""Private chat menus for the factory and each independently owned child bot."""
import asyncio
import re
import time

from .service import Delivery, TelegramFailure, action, inline

DENIED_UPLOAD = 'Hanya pemilik dan admin yang dapat membuat link.'
FILES = ('document', 'photo', 'video', 'audio', 'animation', 'voice', 'video_note', 'sticker')


def command(message):
    text = message.get('text', '')
    parts = text.split(maxsplit=1)
    return (parts[0].split('@')[0].lower() if parts else '', parts[1] if len(parts) > 1 else '')


def private_subject(update):
    callback = update.get('callback_query')
    message = callback.get('message', {}) if callback else update.get('message', {})
    user = (callback or message).get('from', {}).get('id')
    chat = message.get('chat', {})
    if not user or chat.get('id') != user or chat.get('type', 'private') != 'private':
        return None
    return user, message, callback


class BaseUI:
    def __init__(self, db, api):
        self.db, self.api = db, api
        self.pending = {}

    async def text(self, user, text, buttons=None):
        args = {'chat_id': user, 'text': text}
        if buttons is not None:
            args['reply_markup'] = inline(buttons)
        return await self.api.call('sendMessage', **args)

    def wait(self, user, kind, **data):
        self.pending[user] = {'kind': kind, 'expires': time.monotonic()+600, **data}

    def state(self, user):
        state = self.pending.get(user)
        if state and state['expires'] < time.monotonic():
            self.pending.pop(user, None)
            return None
        return state

    async def handle(self, update):
        subject = private_subject(update)
        if subject is None:
            return
        user, message, callback = subject
        try:
            if callback:
                await self.api.call('answerCallbackQuery', callback_query_id=callback['id'])
                await self.callback(user, callback.get('data', ''), message)
            else:
                cmd, _ = command(message)
                if cmd == '/cancel':
                    self.pending.pop(user, None)
                    await self.text(user, 'Dibatalkan.')
                else:
                    await self.message(user, message)
        except (ValueError, PermissionError) as exc:
            await self.text(user, str(exc))
        except TelegramFailure:
            await self.text(user, 'Telegram belum dapat memproses permintaan. Periksa akses bot lalu coba lagi.')


class MasterUI(BaseUI):
    def __init__(self, db, api, manager):
        super().__init__(db, api)
        self.manager = manager

    async def menu(self, user):
        buttons = [[action('Buat / Deploy Bot', 'm:create')], [action('Bot Saya', 'm:mine:0')]]
        if user == self.db.master_owner:
            buttons += [[action('Tambah Izin', 'm:grant'), action('Cabut Izin', 'm:revoke')],
                        [action('Daftar Pengguna', 'm:users:0')], [action('Semua Bot', 'm:bots:0')]]
        await self.text(user, 'Zeisss SubGate — bot induk\nMaintained by Zeisss\n'
                        'Gunakan /buatbot untuk deploy dan /cancel untuk membatalkan input.', buttons)

    async def begin(self, user):
        if not self.db.allowed(user):
            raise PermissionError('Kamu belum mendapat izin membuat bot.')
        self.wait(user, 'deploy', step='api_id')
        await self.text(user, 'Masukkan API ID milikmu. Setiap deploy memerlukan API ID, API hash, dan token lagi.')

    async def listing(self, user, page, all_bots=False):
        if all_bots:
            self.db.master(user)
        rows = self.db.bots(None if all_bots else user)
        page = max(0, page)
        subset = rows[page*8:(page+1)*8]
        lines = ['Daftar bot:']
        buttons = []
        for bot in subset:
            status = 'aktif' if bot['id'] in self.manager.running else 'berhenti'
            lines.append(f"@{bot['username']} — {status} — pemilik {bot['owner']}")
            if all_bots:
                active = bot['id'] in self.manager.running
                buttons.append([action(('Hentikan ' if active else 'Aktifkan ')+f"@{bot['username']}",
                                       f"m:toggle:{bot['id']}:{0 if active else 1}")])
        prefix = 'm:bots' if all_bots else 'm:mine'
        nav = []
        if page:
            nav.append(action('Sebelumnya', f'{prefix}:{page-1}'))
        if (page+1)*8 < len(rows):
            nav.append(action('Berikutnya', f'{prefix}:{page+1}'))
        if nav:
            buttons.append(nav)
        await self.text(user, '\n'.join(lines) if subset else 'Belum ada bot.', buttons)

    async def callback(self, user, data, message):
        if data == 'm:create':
            return await self.begin(user)
        if data.startswith('m:mine:'):
            return await self.listing(user, int(data.split(':')[2]))
        self.db.master(user)
        if data in ('m:grant', 'm:revoke'):
            self.wait(user, data.split(':')[1])
            await self.text(user, 'Masukkan ID Telegram pengguna (angka positif).')
        elif data.startswith('m:users:'):
            page = max(0, int(data.split(':')[2]))
            rows = self.db.creators()
            lines = [f"{r['id']} — {'diizinkan' if r['allowed'] else 'dicabut'}" for r in rows[page*20:(page+1)*20]]
            nav = []
            if page:
                nav.append(action('Sebelumnya', f'm:users:{page-1}'))
            if (page+1)*20 < len(rows):
                nav.append(action('Berikutnya', f'm:users:{page+1}'))
            await self.text(user, '\n'.join(lines) or 'Belum ada pengguna.', [nav] if nav else [])
        elif data.startswith('m:bots:'):
            await self.listing(user, int(data.split(':')[2]), True)
        elif data.startswith('m:toggle:'):
            _, _, bot, active = data.split(':')
            await self.manager.toggle(user, int(bot), bool(int(active)))
            await self.text(user, 'Status bot diperbarui.')

    async def message(self, user, message):
        cmd, _ = command(message)
        if cmd in ('/start', '/setting', '/settings', '/help'):
            self.pending.pop(user, None)
            return await self.menu(user)
        if cmd == '/buatbot':
            return await self.begin(user)
        state = self.state(user)
        if not state:
            return await self.text(user, 'Gunakan /buatbot atau /start.')
        text = message.get('text', '').strip()
        if state['kind'] == 'grant':
            self.db.grant(user, int(text))
            self.pending.pop(user)
            return await self.text(user, 'Izin diberikan sampai kamu mencabutnya. Bot lama perlu deploy ulang.')
        if state['kind'] == 'revoke':
            await self.manager.revoke(user, int(text))
            self.pending.pop(user)
            return await self.text(user, 'Izin dicabut. Semua bot pengguna dihentikan; data tetap disimpan.')
        if state['kind'] == 'deploy':
            if not self.db.allowed(user):
                self.pending.pop(user)
                raise PermissionError('Izin kamu sudah dicabut.')
            if state['step'] == 'api_id':
                api_id = int(text)
                if api_id <= 0:
                    raise ValueError('API ID harus angka positif.')
                state.update(api_id=api_id, step='api_hash')
                await self.text(user, 'Masukkan API hash milikmu.')
            elif state['step'] == 'api_hash':
                if not re.fullmatch(r'[a-fA-F0-9]{32}', text):
                    raise ValueError('API hash harus 32 karakter heksadesimal.')
                state.update(api_hash=text, step='token')
                await self.text(user, 'Masukkan token bot dari @BotFather.')
            else:
                from .telegram import TOKEN
                if not TOKEN.fullmatch(text):
                    raise ValueError('Format token tidak valid. Masukkan token dari @BotFather.')
                self.pending.pop(user)
                await self.text(user, 'Memvalidasi kredensial dan menjalankan bot…')
                me = await self.manager.deploy(user, state['api_id'], state['api_hash'], text)
                await self.text(user, f"@{me['username']} sudah aktif. Buka bot itu, tekan Start, lalu /setting.")


class ChildUI(BaseUI):
    def __init__(self, db, bot, api):
        super().__init__(db, api)
        self.bot = bot
        self.delivery = Delivery(db, bot, api)
        self.broadcasting = False

    async def settings_menu(self, user):
        self.db.owner(self.bot, user)
        s = self.db.settings(self.bot)
        buttons = [
            [action('Channel Database', 's:database'), action('ForceSubs', 's:targets')],
            [action('Admin Pembuat Link', 's:admins')],
            [action('Teks Sambutan', 's:welcome'), action('Foto Sambutan', 's:welcome_photo')],
            [action('Hapus Foto Sambutan', 's:clear_photo')],
            [action('Pesan Wajib Join', 's:force_message')],
            [action('Proteksi: '+('Aktif' if s['protection'] else 'Nonaktif'), 's:protection')],
            [action('Durasi Hapus Otomatis', 's:delete_seconds'), action('Nonaktifkan Hapus', 's:no_delete')],
            [action('Pesan Penghapusan', 's:delete_notice')],
            [action('Broadcast', 's:broadcast')],
        ]
        duration = f"{s['delete_seconds']//60} menit" if s['delete_seconds'] else 'nonaktif'
        await self.text(user, f"Pengaturan @{self.db.bot(self.bot)['username']}\n"
                        f"Database: {s['database'] or 'belum diatur'}\nHapus otomatis: {duration}", buttons)

    async def targets_menu(self, user):
        self.db.owner(self.bot, user)
        targets = self.db.targets(self.bot)
        buttons = [[action('Tambah Channel/Group', 's:add_target')]]
        for item in targets:
            buttons.append([action(f"Hapus {item['kind']} {item['chat']}", f"s:remove_target:{item['chat']}")])
        await self.text(user, f'ForceSubs: {len(targets)}/4. Semua wajib diikuti.', buttons)

    async def admins_menu(self, user):
        self.db.owner(self.bot, user)
        admins = self.db.admins(self.bot)
        # Input-based removal avoids an unbounded Telegram keyboard.
        await self.text(user, 'Admin: '+(', '.join(map(str, admins)) or 'belum ada'),
                        [[action('Tambah ID Admin', 's:add_admin'), action('Hapus ID Admin', 's:remove_admin')]])

    async def begin_broadcast(self, user):
        self.db.owner(self.bot, user)
        if self.broadcasting:
            raise ValueError('Broadcast sebelumnya masih berlangsung.')
        self.wait(user, 'broadcast')
        await self.text(user, 'Kirim/teruskan pesan untuk broadcast, atau /cancel.')

    async def callback(self, user, data, message):
        if data.startswith('get:'):
            return await self.delivery.deliver(user, data[4:])
        if data == 'b:done':
            return await self.finish_batch(user)
        self.db.owner(self.bot, user)
        if data == 's:menu':
            self.pending.pop(user, None)
            return await self.settings_menu(user)
        if data == 's:targets':
            return await self.targets_menu(user)
        if data == 's:admins':
            return await self.admins_menu(user)
        if data.startswith('s:remove_target:'):
            self.db.remove_target(self.bot, user, int(data.split(':')[2]))
            return await self.targets_menu(user)
        if data == 's:protection':
            self.db.setting(self.bot, user, 'protection', not self.db.settings(self.bot)['protection'])
            return await self.settings_menu(user)
        if data in ('s:clear_photo', 's:no_delete'):
            name, value = ('welcome_photo', None) if data == 's:clear_photo' else ('delete_seconds', 0)
            self.db.setting(self.bot, user, name, value)
            return await self.settings_menu(user)
        if data == 's:broadcast':
            return await self.begin_broadcast(user)
        if data == 's:send_broadcast':
            state = self.state(user)
            if not state or state['kind'] != 'broadcast_confirm':
                raise ValueError('Tidak ada broadcast yang menunggu.')
            self.pending.pop(user)
            return await self.broadcast(user, state['message'])
        key = data.removeprefix('s:')
        prompts = {
            'database': 'Masukkan ID channel database. Tambahkan bot sebagai admin dengan izin mengirim dan menghapus pesan.',
            'add_target': 'Masukkan ID channel/supergroup ForceSubs. Bot harus admin dengan izin mengundang pengguna.',
            'add_admin': 'Masukkan ID Telegram admin baru (angka positif).',
            'remove_admin': 'Masukkan ID Telegram admin yang ingin dihapus.',
            'welcome': 'Kirim teks sambutan baru (maksimal 1000 karakter).',
            'welcome_photo': 'Kirim foto untuk pesan sambutan.',
            'force_message': 'Kirim teks wajib join (maksimal 1000 karakter).',
            'delete_seconds': 'Masukkan durasi dalam menit: 1–2879. Isi 0 untuk menonaktifkan.',
            'delete_notice': 'Kirim teks pemberitahuan. Gunakan {durasi} untuk waktu penghapusan (maksimal 1000 karakter).',
        }
        if key in prompts:
            self.wait(user, 'setting', key=key)
            await self.text(user, prompts[key]+'\n/cancel untuk membatalkan.')

    async def welcome(self, user):
        settings = self.db.settings(self.bot)
        if settings['welcome_photo']:
            photo = settings['welcome_photo']
            await self.api.call('sendPhoto', chat_id=user, photo=photo['file_id'], caption=settings['welcome'])
        else:
            await self.text(user, settings['welcome'])

    async def message(self, user, message):
        self.db.add_user(self.bot, user)
        cmd, arg = command(message)
        if cmd in ('/setting', '/settings'):
            self.pending.pop(user, None)
            return await self.settings_menu(user)
        if cmd == '/start':
            self.pending.pop(user, None)
            return await self.delivery.deliver(user, arg) if arg else await self.welcome(user)
        if cmd == '/help':
            return await self.text(user, 'Buka link file untuk mengambil isinya.\n'
                'Pemilik/admin: kirim file atau /batch, lalu Selesai.\nPemilik: /setting dan /broadcast.\n/cancel untuk batal.')
        if cmd == '/broadcast':
            self.db.owner(self.bot, user)
            if message.get('reply_to_message'):
                self.wait(user, 'broadcast_confirm', message=message['reply_to_message']['message_id'])
                return await self.text(user, 'Kirim pesan balasan itu ke semua pengguna?',
                                       [[action('Kirim Broadcast', 's:send_broadcast')]])
            return await self.begin_broadcast(user)
        if cmd == '/batch':
            if not self.db.can_upload(self.bot, user):
                raise PermissionError(DENIED_UPLOAD)
            self.wait(user, 'batch', sources=[])
            return await self.text(user, 'Kirim file satu per satu sesuai urutan. Tekan Selesai setelah semua terkirim.',
                                   [[action('Selesai', 'b:done')]])
        state = self.state(user)
        if state and state['kind'] == 'setting':
            self.db.owner(self.bot, user)
            await self.save_setting(user, message, state['key'])
            self.pending.pop(user, None)
            return await self.settings_menu(user)
        if state and state['kind'] == 'broadcast':
            self.db.owner(self.bot, user)
            self.wait(user, 'broadcast_confirm', message=message['message_id'])
            return await self.text(user, 'Kirim pesan ini ke semua pengguna?',
                                   [[action('Kirim Broadcast', 's:send_broadcast')]])
        if any(kind in message for kind in FILES) or message.get('forward_origin'):
            if not self.db.can_upload(self.bot, user):
                raise PermissionError(DENIED_UPLOAD)
            source = self.db.settings(self.bot)['database']
            if not source:
                raise ValueError('Pemilik perlu mengatur channel database melalui /setting terlebih dahulu.')
            await self.delivery.validate_chat(source, database=True)
            saved = await self.api.call('copyMessage', chat_id=source, from_chat_id=user,
                                        message_id=message['message_id'])
            pair = (source, saved['message_id'])
            if state and state['kind'] == 'batch':
                state['sources'].append(pair)
                state['expires'] = time.monotonic()+600
                return await self.text(user, f"File ke-{len(state['sources'])} tersimpan.",
                                       [[action('Selesai', 'b:done')]])
            return await self.share(user, [pair])

    async def save_setting(self, user, message, key):
        text = message.get('text', '').strip()
        if key == 'database':
            chat = int(text)
            await self.delivery.validate_chat(chat, database=True)
            self.db.setting(self.bot, user, 'database', chat)
        elif key == 'add_target':
            chat = int(text)
            targets = self.db.targets(self.bot)
            if len(targets) >= 4 and chat not in [t['chat'] for t in targets]:
                raise ValueError('Maksimal 4 channel/grup ForceSubs.')
            target = await self.delivery.validate_chat(chat)
            self.db.target(self.bot, user, **target)
        elif key in ('add_admin', 'remove_admin'):
            self.db.admin(self.bot, user, int(text), key == 'add_admin')
        elif key == 'welcome_photo':
            if not message.get('photo'):
                raise ValueError('Kirim foto, bukan dokumen atau teks.')
            self.db.setting(self.bot, user, key, {'file_id': message['photo'][-1]['file_id']})
        elif key == 'delete_seconds':
            self.db.setting(self.bot, user, key, int(text)*60)
        else:
            self.db.setting(self.bot, user, key, text)

    async def finish_batch(self, user):
        if not self.db.can_upload(self.bot, user):
            raise PermissionError(DENIED_UPLOAD)
        state = self.state(user)
        if not state or state['kind'] != 'batch' or not state['sources']:
            raise ValueError('Belum ada file dalam batch. Gunakan /batch terlebih dahulu.')
        await self.share(user, state['sources'])
        self.pending.pop(user, None)

    async def share(self, user, sources):
        key = self.db.link(self.bot, user, sources)
        await self.text(user, f"Link file:\nhttps://t.me/{self.db.bot(self.bot)['username']}?start={key}")

    async def broadcast(self, user, message_id):
        self.db.owner(self.bot, user)
        if self.broadcasting:
            raise ValueError('Broadcast sebelumnya masih berlangsung.')
        self.broadcasting = True
        success = failed = 0
        try:
            await self.text(user, 'Broadcast dimulai…')
            for target in self.db.users(self.bot):
                try:
                    await self.api.call('copyMessage', chat_id=target, from_chat_id=user, message_id=message_id)
                    success += 1
                except TelegramFailure:
                    failed += 1
                await asyncio.sleep(0.05)
            await self.text(user, f'Broadcast selesai. Berhasil: {success}. Gagal: {failed}.')
        finally:
            self.broadcasting = False
