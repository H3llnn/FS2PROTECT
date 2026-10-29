"""Factory menus and confirmed owner-only lifecycle actions."""
import re
import time
from .ui_base import BaseUI, command
from .copy import h, panel, button, link_button, nav

HOME = [button('⌂ Menu Utama', 'm:menu')]
API_BUTTON = link_button('🔑 Ambil API ID & Hash', 'https://my.telegram.org/auth')


class MasterUI(BaseUI):
    def __init__(self, db, api, manager):
        super().__init__(db, api)
        self.manager = manager

    async def menu(self, user):
        self.clear(user)
        buttons = [[button('＋ Buat / Deploy Bot', 'm:create')], [button('▦ Bot Saya', 'm:mine:0')]]
        if user == self.db.master_owner:
            buttons += [[button('🔑 Tambah Izin', 'm:grant'), button('🔒 Cabut Izin', 'm:revoke')],
                        [button('👥 Daftar Pengguna', 'm:users:0')], [button('🤖 Semua Bot', 'm:bots:0')]]
        await self.text(user, panel('Zeisss SubGate', '<i>Ruang kendali bot pribadimu.</i>\n\n'
            f'Hai, {h(self.names.get(user, "teman"))} 👋\n'
            'Semua botmu, satu tempat. Buat bot baru atau kelola yang sudah aktif lewat menu di bawah.\n\n'
            '🔐 Akses khusus pengguna yang mendapat izin.\n\n<i>Maintained by Zeisss</i>'), buttons)

    async def begin(self, user, kind=None):
        if not self.db.allowed(user):
            self.clear(user)
            return await self.text(user, panel('Akses khusus 🔐',
                'Kamu belum mendapat izin untuk membuat bot.\nHubungi pengelola untuk meminta akses, ya.'), [HOME])
        kinds=[k for k in ('forcesubs','payment') if self.db.allowed(user,k)]
        if kind is None and len(kinds)>1:
            self.clear(user)
            return await self.text(user,panel('Pilih jenis bot ✨','Bot mana yang ingin kamu jalankan?'),
                [[button('ForceSubs','m:kind:forcesubs'),button('Payment · Percobaan','m:kind:payment')],HOME])
        kind=kind or kinds[0]
        if kind not in kinds: raise PermissionError('Kamu belum mendapat izin untuk jenis bot ini.')
        self.wait(user, 'deploy', step='api_id', bot_kind=kind, back='m:back')
        await self.deploy_prompt(user)

    async def deploy_prompt(self, user):
        state = self.state(user)
        if state['step'] == 'api_id':
            text = panel('Siapkan bot barumu', 'Kita mulai dari <b>API ID</b> dulu 🔑\nKirim API ID milikmu untuk melanjutkan.')
            buttons = [[API_BUTTON], [button('✕ Batal', 'x:cancel')]]
        elif state['step'] == 'api_hash':
            text = panel('Lanjut, API Hash 🔐', 'API ID sudah diterima.\nSekarang kirim <b>API Hash</b> milikmu untuk melanjutkan.')
            buttons = [[API_BUTTON], *nav('m:back')]
        else:
            text = panel('Satu langkah lagi 🤖', 'Sekarang kirim <b>token bot</b> yang ingin kamu jalankan.')
            buttons = [[link_button('🤖 Buka BotFather', 'https://t.me/BotFather')], *nav('m:back')]
        await self.text(user, text, buttons)

    async def refresh_name(self, row):
        if row['id'] in self.manager.running or not row.get('name'):
            try:
                name = await self.manager.lookup_name(row['id'])
                if name:
                    self.db.display_name(row['id'], name)
                    row['name'] = name
            except Exception:
                pass
        return row.get('name') or 'Bot Telegram'

    async def listing(self, user, page, all_bots=False, owner=None):
        if all_bots or owner is not None:
            self.db.master(user)
        rows = self.db.bots(None if all_bots else (owner if owner is not None else user))
        page = max(0, min(page, max(0, (len(rows)-1)//8)))
        prefix = 'bots' if all_bots else (f'owned:{owner}' if owner is not None else 'mine')
        self.clear(user)
        if not rows:
            return await self.text(user, panel('Ruangmu masih kosong ✨',
                'Belum ada bot di sini.\nYuk, mulai dengan bot pertamamu.'), [[button('＋ Buat Bot', 'm:create')], HOME])
        active = sum(row['id'] in self.manager.running for row in rows)
        title = 'Pusat kendali bot 🤖' if all_bots else 'Koleksi botmu 🤖'
        body = (f'<b>Total:</b> {len(rows)}\n<b>🟢 Berjalan:</b> {active}\n<b>⚫ Berhenti:</b> {len(rows)-active}'
                if all_bots else f'Kamu punya <b>{len(rows)} bot</b>.')
        buttons = []
        for row in rows[page*8:(page+1)*8]:
            name = await self.refresh_name(row)
            status = '🟢' if row['id'] in self.manager.running else '⚫'
            buttons.append([button(f'{status} {name}', f'm:detail:{row["id"]}:{prefix}:{page}')])
        nav_buttons = []
        if page:
            nav_buttons.append(button('‹ Sebelumnya', f'm:{prefix}:{page-1}'))
        if (page+1)*8 < len(rows):
            nav_buttons.append(button('Berikutnya ›', f'm:{prefix}:{page+1}'))
        if nav_buttons:
            buttons.append(nav_buttons)
        buttons.append(HOME)
        await self.text(user, panel(title, body+'\n\nPilih salah satu untuk melihat detailnya.'), buttons)

    async def detail(self, user, bot, context='mine', page=0):
        row = self.db.bot(bot)
        if context == 'mine':
            self.db.owner(bot, user)
        else:
            self.db.master(user)
            if context.startswith('owned:') and row['owner'] != int(context.split(':')[1]):
                raise PermissionError('Bot bukan milik pengguna ini.')
        self.clear(user)
        name = await self.refresh_name(row)
        active = bot in self.manager.running
        status = '🟢 Aktif' if active else '⚫ Berhenti'
        back = f'm:{context}:{page}'
        buttons = []
        if user == self.db.master_owner and context != 'mine':
            if active:
                buttons.append([button('⏸ Hentikan Bot', f'm:stop:{bot}:{context}:{page}')])
            elif self.db.allowed(row['owner']) and not row['redeploy_required']:
                buttons.append([button('▶️ Aktifkan Bot', f'm:on:{bot}:{context}:{page}')])
        buttons += [[link_button('↗ Buka Bot', f'https://t.me/{row["username"]}')],
                    [button('‹ Bot Saya' if context == 'mine' else '‹ Kembali', back)], HOME]
        body = (f'<b>Nama:</b> {h(name)}\n<b>Username:</b> @{h(row["username"])}\n'
                f'<b>Jenis:</b> {h(row["kind"])}\n<b>ID bot:</b> {bot}\n<b>Pemilik:</b> {row["owner"]}\n<b>Status:</b> {status}')
        if context == 'mine':
            body += '\n\nPengaturan tersedia melalui /setting di bot anak.'
        if row['redeploy_required']:
            body += '\n\nPemilik perlu deploy ulang setelah mendapat izin kembali.'
        await self.text(user, panel('Detail botmu 🤖' if context == 'mine' else 'Detail bot 🤖', body), buttons)

    async def users_menu(self, user, page=0):
        self.db.master(user)
        self.clear(user)
        rows = self.db.creators()
        page = max(0, min(page, max(0, (len(rows)-1)//12)))
        active = sum(bool(r['allowed']) for r in rows)
        buttons = [[button(('🟢' if r['allowed'] else '🔒')+f' {r["id"]}', f'm:user:{r["id"]}')]
                   for r in rows[page*12:(page+1)*12]]
        pages = []
        if page:
            pages.append(button('‹ Sebelumnya', f'm:users:{page-1}'))
        if (page+1)*12 < len(rows):
            pages.append(button('Berikutnya ›', f'm:users:{page+1}'))
        if pages:
            buttons.append(pages)
        buttons.append(HOME)
        await self.text(user, panel('Kelola akses pengguna 👥',
            f'<b>Diizinkan:</b> {active}\n<b>Dicabut:</b> {len(rows)-active}\n\n'
            'Pilih pengguna untuk melihat akses dan bot miliknya.'), buttons)

    async def user_detail(self, user, target):
        self.db.master(user)
        self.clear(user)
        allowed = self.db.allowed(target)
        buttons = [[button('🔒 Cabut Akses' if allowed else '🔑 Beri Akses',
                          f'm:revoke_ask:{target}' if allowed else f'm:grant_id:{target}')],
                   [button('Ubah Jenis Izin',f'm:grant_id:{target}')],
                   [button('🤖 Bot Pengguna', f'm:owned:{target}:0')],
                   [button('‹ Daftar Pengguna', 'm:users:0')], HOME]
        await self.text(user, panel('Detail akses pengguna 👤',
            f'<b>ID:</b> {target}\n<b>Akses:</b> {"🟢 Diizinkan" if allowed else "🔒 Dicabut"}\n'
            f'<b>Jenis izin:</b> {h(", ".join(k for k in ("forcesubs","payment") if self.db.allowed(target,k)) or "Tidak ada")}\n<b>Jumlah bot:</b> {len(self.db.bots(target))}'), buttons)

    async def ask_revoke(self, user, target, kind=None):
        self.db.master(user)
        if target == self.db.master_owner:
            raise ValueError('Akses pemilik bot induk tidak dapat dicabut.')
        kinds=[k for k in ('forcesubs','payment') if self.db.allowed(target,k)]
        if kind is None and len(kinds)==1: kind=kinds[0]
        if kind is None:
            self.clear(user)
            return await self.text(user,panel('Cabut izin mana? 🔐',f'Pengguna: {target}'),
                [[button('ForceSubs',f'm:revoke_type:{target}:forcesubs'),button('Payment',f'm:revoke_type:{target}:payment')],
                 [button('Keduanya',f'm:revoke_type:{target}:both')],HOME])
        if kind not in ('forcesubs','payment','both'): raise ValueError('Jenis tidak dikenal.')
        self.wait(user,'revoke_confirm',target=target,bot_kind=kind,back=f'm:user:{target}')
        await self.text(user,panel('Cabut akses pengguna? 🔐',
            f'Pengguna: <b>{target}</b>\nJenis: <b>{h(kind)}</b>\nBot terkait akan dihentikan dan pesanan belum dibayar dibatalkan. Data tetap disimpan. Setelah izin pulih, pemilik perlu deploy ulang.'),
            [[button('Cabut Akses',f'm:revoke_yes:{target}:{kind}'),button('Kembali',f'm:user:{target}')]])

    async def grant(self, user, target):
        self.db.master(user)
        self.wait(user,'grant_kind',target=target)
        await self.text(user,panel('Pilih izin pengguna 🔑',f'ID: {target}\nJenis izin ini menggantikan izin sebelumnya. Bot dari jenis yang dicabut akan berhenti.'),
            [[button('ForceSubs',f'm:grant_kind:{target}:forcesubs'),button('Payment',f'm:grant_kind:{target}:payment')],
             [button('Keduanya',f'm:grant_kind:{target}:both')],HOME])

    async def callback(self, user, data, message):
        if data == 'x:cancel':
            return await self.cancelled(user)
        if data == 'm:menu':
            return await self.menu(user)
        if data == 'm:create':
            return await self.begin(user)
        if data.startswith('m:kind:'):
            return await self.begin(user,data.split(':')[2])
        if data == 'm:back':
            state = self.state(user)
            if not state or state['kind'] != 'deploy':
                return await self.menu(user)
            if state['step'] == 'token':
                state['step'] = 'api_hash'
                state.pop('api_hash', None)
            elif state['step'] == 'api_hash':
                state['step'] = 'api_id'
                state.pop('api_id', None)
            else:
                return await self.menu(user)
            return await self.deploy_prompt(user)
        parts = data.split(':')
        if data.startswith('m:mine:'):
            return await self.listing(user, int(parts[2]))
        if data.startswith('m:detail:'):
            context = ':'.join(parts[3:-1])
            return await self.detail(user, int(parts[2]), context, int(parts[-1]))
        self.db.master(user)
        if data in ('m:grant', 'm:revoke'):
            self.wait(user, parts[1], back='m:menu')
            if parts[1] == 'grant':
                text = panel('Buka akses baru 🔑', 'Kirim <b>ID Telegram pengguna</b> yang ingin kamu izinkan membuat bot.\nAkses berlaku sampai kamu mencabutnya.')
            else:
                text = panel('Cabut akses pengguna 🔐', 'Kirim <b>ID Telegram pengguna</b> yang ingin kamu cabut aksesnya.')
            return await self.text(user, text, nav('m:menu'))
        if data.startswith('m:users:'):
            return await self.users_menu(user, int(parts[2]))
        if data.startswith('m:user:'):
            return await self.user_detail(user, int(parts[2]))
        if data.startswith('m:grant_kind:'):
            state=self.state(user)
            if not state or state['kind']!='grant_kind' or state['target']!=int(parts[2]): raise ValueError('Konfirmasi izin berakhir.')
            await self.manager.grant(user,int(parts[2]),parts[3])
            self.clear(user)
            return await self.text(user,panel('Izin diberikan ✅','Jenis izin: '+h(parts[3])),[HOME])
        if data.startswith('m:grant_id:'):
            return await self.grant(user, int(parts[2]))
        if data.startswith('m:revoke_type:'):
            return await self.ask_revoke(user,int(parts[2]),parts[3])
        if data.startswith('m:revoke_ask:'):
            return await self.ask_revoke(user, int(parts[2]))
        if data.startswith('m:revoke_yes:'):
            target = int(parts[2])
            state = self.state(user)
            if not state or state['kind'] != 'revoke_confirm' or state['target'] != target or (len(parts)==4 and state.get('bot_kind')!=parts[3]):
                raise ValueError('Konfirmasi sudah berakhir. Pilih pengguna kembali.')
            await self.manager.revoke(user, target,state['bot_kind'])
            self.clear(user)
            return await self.text(user, panel('Akses sudah dicabut 🔒',
                f'Akses pengguna <b>{target}</b> telah dinonaktifkan.\n'
                'Bot dari jenis izin tersebut dihentikan, dan datanya tetap tersimpan.'),
                [[button('‹ Daftar Pengguna', 'm:users:0')], HOME])
        if data.startswith('m:bots:'):
            return await self.listing(user, int(parts[2]), True)
        if data.startswith('m:owned:'):
            return await self.listing(user, int(parts[3]), owner=int(parts[2]))
        if data.startswith(('m:stop:', 'm:stop_yes:', 'm:on:')):
            bot, context, page = int(parts[2]), ':'.join(parts[3:-1]), int(parts[-1])
            row = self.db.bot(bot)
            back = f'm:detail:{bot}:{context}:{page}'
            name = h(await self.refresh_name(row))
            if parts[1] == 'stop':
                self.wait(user, 'stop_confirm', bot=bot, back=back)
                return await self.text(user, panel('Hentikan bot ini? ⏸',
                    f'<b>{name}</b> akan berhenti melayani pengguna.\nPengaturan dan link tetap tersimpan.'),
                    [[button('⏸ Hentikan', f'm:stop_yes:{bot}:{context}:{page}'), button('‹ Kembali', back)]])
            if parts[1] == 'stop_yes':
                state = self.state(user)
                if not state or state['kind'] != 'stop_confirm' or state['bot'] != bot:
                    raise ValueError('Konfirmasi sudah berakhir. Pilih bot kembali.')
                await self.manager.toggle(user, bot, False)
                self.clear(user)
                return await self.text(user, panel('Bot sudah dihentikan ⚫',
                    f'<b>{name}</b> sedang berhenti.\nKamu bisa mengaktifkannya kembali melalui halaman detail bot.'),
                    [[button('‹ Detail Bot', back)]])
            try:
                await self.manager.toggle(user, bot, True)
            except (ValueError, PermissionError):
                return await self.text(user, panel('Bot belum bisa diaktifkan 🔧',
                    f'Ada kendala saat menjalankan <b>{name}</b>.\nPeriksa token, izin pemilik, dan koneksi server, lalu coba lagi.'),
                    [[button('↻ Coba Lagi', data), button('‹ Detail Bot', back)]])
            return await self.text(user, panel('Botmu kembali aktif 🟢',
                f'<b>{name}</b> siap melayani pengguna lagi.\nPengaturan dan link sebelumnya tetap tersedia.'),
                [[link_button('↗ Buka Bot', f'https://t.me/{row["username"]}'), button('‹ Detail Bot', back)]])

    async def message(self, user, message):
        cmd, _ = command(message)
        if cmd in ('/start', '/setting', '/settings', '/help'):
            return await self.menu(user)
        if cmd == '/buatbot':
            return await self.begin(user)
        state = self.state(user)
        if not state:
            return await self.menu(user)
        text = message.get('text', '').strip()
        if state['kind'] == 'grant':
            return await self.grant(user, self.positive_id(text))
        if state['kind'] == 'revoke':
            return await self.ask_revoke(user, self.positive_id(text))
        if state['kind'] != 'deploy':
            return
        if not self.db.allowed(user):
            self.clear(user)
            return await self.begin(user)
        if state['step'] == 'api_id':
            state.update(api_id=self.positive_id(text), step='api_hash', expires=time.monotonic()+600)
            return await self.deploy_prompt(user)
        if state['step'] == 'api_hash':
            if not re.fullmatch(r'[a-fA-F0-9]{32}', text):
                raise ValueError('API hash harus 32 karakter heksadesimal.')
            state.update(api_hash=text, step='token', expires=time.monotonic()+600)
            return await self.deploy_prompt(user)
        from .telegram import TOKEN
        if not TOKEN.fullmatch(text):
            raise ValueError('Format token bot belum sesuai. Salin token dari BotFather.')
        self.clear(user)
        await self.text(user, panel('Menyiapkan botmu… ⚙️', 'Sebentar ya, kredensialmu sedang diperiksa.'))
        try:
            me = await self.manager.deploy(user, state['api_id'], state['api_hash'], text,kind=state['bot_kind'])
        except (ValueError, PermissionError):
            return await self.text(user, panel('Botmu belum bisa diaktifkan 🔧',
                'Periksa kembali API ID, API hash, dan token yang kamu masukkan, lalu coba lagi.'),
                [[button('↻ Coba Lagi', 'm:create')], HOME])
        await self.text(user, panel('Botmu siap! ✨',
            f'@{h(me["username"])} berhasil diaktifkan.\nBuka botmu, lalu atur channel dan aksesnya lewat menu pengaturan.'),
            [[link_button('↗ Buka Botmu', f'https://t.me/{me["username"]}'), button('▦ Bot Saya', 'm:mine:0')], HOME])
