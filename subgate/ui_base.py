"""Shared private-chat routing, safe HTML and expiring conversations."""
import asyncio
import time
from collections import defaultdict
from .display import Display
from .copy import h, panel, button, nav
from .service import inline, TelegramFailure

FILES = ('document', 'photo', 'video', 'audio', 'animation', 'voice', 'video_note', 'sticker')

def command(message):
    parts = message.get('text', '').split(maxsplit=1)
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
        self.pending, self.timers, self.names = {}, {}, {}
        self.expired = set()
        self.display = Display(db.conn, api)
        self.screen_locks = defaultdict(asyncio.Lock)

    async def text(self, user, text, buttons=None):
        async with self.screen_locks[user]:
            message = await self.durable(user, text, buttons)
            await self.display.replace(getattr(self, 'bot', 0), user, [message])
            return message

    async def photo_text(self, user, photo, text, buttons=None):
        if not photo:
            return await self.text(user, text, buttons)
        async with self.screen_locks[user]:
            long_caption = len(text.encode('utf-16-le')) // 2 > 1024
            message = await self.api.call('sendPhoto', chat_id=user, photo=photo,
                caption='' if long_caption else text, parse_mode='HTML',
                reply_markup=inline([] if long_caption else (buttons or [])))
            messages = [message]
            if long_caption:
                try:
                    messages.append(await self.durable(user, text, buttons))
                except TelegramFailure:
                    # Preserve the old screen and track the partial new photo for cleanup.
                    with self.db.conn:
                        self.db.conn.execute('INSERT OR IGNORE INTO display_screens VALUES (?,?,?)',
                            (getattr(self, 'bot', 0), user, message['message_id']))
                    raise
            await self.display.replace(getattr(self, 'bot', 0), user, messages)
            return messages[-1]

    async def durable(self, user, text, buttons=None):
        args = {'chat_id': user, 'text': text, 'parse_mode': 'HTML'}
        if buttons is not None:
            args['reply_markup'] = inline(buttons)
        return await self.api.call('sendMessage', **args)

    def clear(self, user):
        self.pending.pop(user, None)
        timer = self.timers.pop(user, None)
        if timer is not None and timer is not asyncio.current_task():
            timer.cancel()
        self.expired.discard(user)

    def wait(self, user, kind, **data):
        self.clear(user)
        state = {'kind': kind, 'expires': time.monotonic()+600, **data}
        self.pending[user] = state
        self.timers[user] = asyncio.create_task(self.expire_after(user, state))

    def state(self, user):
        return self.pending.get(user)

    def expiry_buttons(self, state):
        return [[button('↻ Mulai Lagi', state.get('back', 'm:create')),
                 button('⌂ Menu Utama', 'm:menu')]]

    async def expire(self, user, state):
        if self.pending.get(user) is not state:
            return
        self.clear(user)
        self.expired.add(user)
        await self.text(user, panel('⏳ Sesi pengaturan berakhir',
            'Buka pengaturan lagi untuk melanjutkan, ya. Perubahan yang belum disimpan tidak diterapkan.'), self.expiry_buttons(state))

    async def expire_after(self, user, state):
        try:
            while self.pending.get(user) is state:
                remaining = state['expires'] - time.monotonic()
                if remaining <= 0:
                    return await self.expire(user, state)
                await asyncio.sleep(remaining)
        except (asyncio.CancelledError, TelegramFailure):
            pass

    async def close(self):
        timers = list(self.timers.values())
        for task in timers:
            task.cancel()
        if timers:
            await asyncio.gather(*timers, return_exceptions=True)
        self.timers.clear()
        self.pending.clear()
        self.expired.clear()

    async def cancelled(self, user):
        self.clear(user)
        await self.text(user, panel('Dibatalkan 🍃',
            'Prosesnya sudah dihentikan.\nKamu bisa mulai lagi kapan saja.'),
            [[button('＋ Buat Bot', 'm:create'), button('⌂ Menu Utama', 'm:menu')]])

    def error_buttons(self, user):
        state = self.state(user)
        return nav(state.get('back', 'm:back')) if state else None

    def error_text(self, exc):
        return panel('Cek sekali lagi, ya 🔎',
            h(exc)+'\n\nKirim ulang data yang sesuai untuk melanjutkan.')

    async def handle(self, update):
        subject = private_subject(update)
        if subject is None:
            return
        user, message, callback = subject
        sender = (callback or message).get('from', {})
        self.names[user] = ' '.join(sender.get(key) or '' for key in ('first_name', 'last_name')).strip() or 'teman'
        try:
            if callback:
                await self.api.call('answerCallbackQuery', callback_query_id=callback['id'])
                state = self.state(user)
                if state and state['expires'] <= time.monotonic():
                    return await self.expire(user, state)
                self.expired.discard(user)
                if callback.get('data') == 'x:cancel':
                    return await self.cancelled(user)
                await self.callback(user, callback.get('data', ''), message)
                return
            cmd, _ = command(message)
            if cmd == '/cancel':
                return await self.cancelled(user)
            state = self.state(user)
            if state and state['expires'] <= time.monotonic():
                return await self.expire(user, state)
            if user in self.expired and not cmd.startswith('/'):
                self.expired.discard(user)
                return await self.text(user, panel('⏳ Sesi pengaturan berakhir',
                    'Buka pengaturan lagi untuk melanjutkan, ya. Perubahan yang belum disimpan tidak diterapkan.'), self.expiry_buttons({}))
            await self.message(user, message)
        except PermissionError as exc:
            await self.text(user, panel('Akses terbatas 🔐', h(exc)))
        except ValueError as exc:
            await self.text(user, self.error_text(exc), self.error_buttons(user))
        except TelegramFailure:
            await self.text(user, panel('Ada kendala sebentar 🔧',
                'Permintaanmu belum bisa diproses.\nCoba lagi beberapa saat lagi, ya.'), self.error_buttons(user))

    def positive_id(self, text):
        try:
            value = int(text)
            if value <= 0:
                raise ValueError
        except (ValueError, TypeError):
            raise ValueError('ID Telegram harus berupa angka positif.') from None
        return value
