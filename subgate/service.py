"""File delivery and durable expiry; Telegram operations are injected."""
import asyncio
import time


class TelegramFailure(Exception):
    def __init__(self, code, description, retry_after=None):
        self.code = code
        self.description = description
        self.retry_after = retry_after
        super().__init__(description)


def inline(rows):
    return {'inline_keyboard': rows}


def action(text, data):
    return {'text': text, 'callback_data': data}


class Delivery:
    def __init__(self, db, bot, api, clock=time.time):
        self.db, self.bot, self.api, self.clock = db, bot, api, clock
        self.locks = {}

    async def text(self, chat, text, **kwargs):
        return await self.api.call('sendMessage', chat_id=chat, text=text, **kwargs)

    async def incident(self, scope, broken):
        if self.db.incident(self.bot, scope, broken):
            text = (f'Gangguan akses {scope}. Periksa izin admin, ketersediaan pesan sumber, dan koneksi Telegram.'
                    if broken else f'Akses {scope} sudah pulih, bot kembali normal.')
            try:
                await self.text(self.db.bot(self.bot)['owner'], text)
            except TelegramFailure:
                # Owner may not have started this child yet. Incident stays deduplicated.
                pass

    async def check_admin(self, chat):
        member = await self.api.call('getChatMember', chat_id=chat, user_id=self.bot)
        if member['status'] not in ('administrator', 'creator'):
            raise TelegramFailure(403, 'Bot bukan admin.')
        return member

    async def missing(self, user):
        if self.db.can_upload(self.bot, user):
            return []
        missing = []
        for target in self.db.targets(self.bot):
            scope = f"chat:{target['chat']}"
            try:
                await self.check_admin(target['chat'])
            except TelegramFailure:
                await self.incident(scope, True)
                raise
            await self.incident(scope, False)
            membership_scope = f"membership:{target['chat']}"
            try:
                member = await self.api.call('getChatMember', chat_id=target['chat'], user_id=user)
                status = member.get('status')
                if status not in ('creator', 'administrator', 'member', 'restricted', 'left', 'kicked'):
                    raise TelegramFailure(500, 'Status keanggotaan tidak dikenal.')
                joined = status in ('creator', 'administrator', 'member') or (
                    status == 'restricted' and member.get('is_member') is True)
            except TelegramFailure:
                await self.incident(membership_scope, True)
                raise
            await self.incident(membership_scope, False)
            if not joined:
                missing.append(target)
        return missing

    async def deliver(self, user, key):
        lock = self.locks.setdefault(user, asyncio.Lock())
        if lock.locked():
            return False
        async with lock:
            return await self._deliver(user, key)

    async def _deliver(self, user, key):
        sources = self.db.sources(self.bot, key)
        if not sources:
            await self.text(user, 'Link tidak valid atau tidak ditemukan.')
            return False
        settings = self.db.settings(self.bot)
        try:
            missing = await self.missing(user)
        except TelegramFailure:
            await self.text(user, 'Layanan sedang mengalami gangguan. Silakan coba lagi nanti.')
            return False
        if missing:
            buttons = [[{'text': 'Join Channel' if item['kind'] == 'channel' else 'Join Group',
                         'url': item['url']}] for item in missing]
            buttons.append([action('Coba Lagi', f'get:{key}')])
            await self.text(user, settings['force_message'], reply_markup=inline(buttons))
            return False
        deadline = self.clock() + settings['delete_seconds']
        sent = 0
        complete = True
        try:
            for source, message in sources:
                try:
                    await self.check_admin(source)
                except TelegramFailure:
                    await self.incident(f'chat:{source}', True)
                    raise
                await self.incident(f'chat:{source}', False)
                try:
                    result = await self.api.call('copyMessage', chat_id=user,
                        from_chat_id=source, message_id=message, protect_content=settings['protection'])
                except TelegramFailure:
                    await self.incident(f'file:{source}:{message}', True)
                    raise
                sent += 1
                if settings['delete_seconds']:
                    self.db.schedule(self.bot, user, result['message_id'], deadline)
                await self.incident(f'file:{source}:{message}', False)
                # Keep batch ordering and stay below Telegram's per-chat send rate.
                if len(sources) > 1:
                    await asyncio.sleep(1.05)
        except TelegramFailure:
            complete = False
            await self.text(user, 'Layanan sedang mengalami gangguan. Silakan coba lagi nanti.')
        finally:
            if sent and settings['delete_seconds']:
                seconds = settings['delete_seconds']
                duration = f'{seconds // 60} menit' if seconds % 60 == 0 else f'{seconds} detik'
                notice = await self.text(user, settings['delete_notice'].format(durasi=duration))
                self.db.schedule(self.bot, user, notice['message_id'], deadline)
        return complete

    async def expire(self, now=None):
        now = self.clock() if now is None else now
        for job in self.db.due(now, self.bot):
            try:
                await self.api.call('deleteMessage', chat_id=job['chat'], message_id=job['message_id'])
            except TelegramFailure as exc:
                if exc.code == 400 and 'message to delete not found' in exc.description.lower():
                    self.db.finish_job(job['id'])
                elif exc.code == 400 and "can't be deleted" in exc.description.lower():
                    await self.incident('penghapusan:melewati-batas-telegram', True)
                    self.db.finish_job(job['id'])
                else:
                    self.db.retry_job(job['id'], now + (exc.retry_after or 60))
            else:
                self.db.finish_job(job['id'])

    async def validate_chat(self, chat, database=False):
        if chat >= 0:
            raise ValueError('Gunakan ID channel/grup negatif, misalnya -1001234567890.')
        info = await self.api.call('getChat', chat_id=chat)
        if info['type'] not in ('channel', 'supergroup'):
            raise ValueError('Gunakan channel atau supergroup Telegram.')
        if database and info['type'] != 'channel':
            raise ValueError('Database harus berupa channel.')
        member = await self.check_admin(chat)
        if database:
            if member['status'] != 'creator' and not member.get('can_post_messages'):
                raise ValueError('Bot memerlukan izin mengirim pesan di channel database.')
            probe = await self.text(chat, 'Zeisss SubGate: pemeriksaan akses database.')
            await self.api.call('deleteMessage', chat_id=chat, message_id=probe['message_id'])
            return info
        if member['status'] != 'creator' and not member.get('can_invite_users'):
            raise ValueError('Bot memerlukan izin mengundang pengguna.')
        url = info.get('invite_link')
        if info.get('username'):
            url = f"https://t.me/{info['username']}"
        if not url:
            invite = await self.api.call('createChatInviteLink', chat_id=chat, name='Zeisss SubGate')
            url = invite['invite_link']
        return {'chat': chat, 'kind': 'channel' if info['type'] == 'channel' else 'group', 'url': url}
