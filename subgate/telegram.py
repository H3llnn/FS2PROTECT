"""Telegram Bot API transport; sensitive request URLs never reach logs."""
import asyncio
import logging
import re
import aiohttp

from .service import TelegramFailure

TOKEN = re.compile(r'^[1-9][0-9]*:[A-Za-z0-9_-]{20,}$')
log = logging.getLogger(__name__)


class API:
    def __init__(self, token):
        if not TOKEN.fullmatch(token):
            raise ValueError('Format token bot tidak valid.')
        self.token = token
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=70))

    async def call(self, method, **params):
        for attempt in range(3):
            try:
                async with self.session.post(
                    f'https://api.telegram.org/bot{self.token}/{method}', json=params
                ) as response:
                    body = await response.json(content_type=None)
            except (aiohttp.ClientError, TimeoutError, ValueError):
                raise TelegramFailure(503, 'Koneksi Telegram gagal; silakan coba lagi.') from None
            if body.get('ok'):
                return body['result']
            code = body.get('error_code', 500)
            retry = body.get('parameters', {}).get('retry_after')
            if code == 429 and attempt < 2 and retry and retry <= 60:
                await asyncio.sleep(retry + 0.1)
                continue
            # Redact credentials even if an upstream error unexpectedly echoes them.
            description = str(body.get('description', 'Telegram gagal merespons.')).replace(self.token, '[redacted]')
            raise TelegramFailure(code, description, retry)

    async def send_photo_bytes(self,chat,data,caption,markup):
        import json
        form=aiohttp.FormData()
        form.add_field('chat_id',str(chat))
        form.add_field('caption',caption)
        form.add_field('reply_markup',json.dumps(markup))
        form.add_field('photo',data,filename='qris.png',content_type='image/png')
        try:
            async with self.session.post(f'https://api.telegram.org/bot{self.token}/sendPhoto',data=form) as response:
                body=await response.json(content_type=None)
        except (aiohttp.ClientError,TimeoutError,ValueError):
            raise TelegramFailure(503,'Pengiriman QRIS belum dapat dipastikan; jangan membayar ulang.') from None
        if not body.get('ok'):
            raise TelegramFailure(body.get('error_code',500),'QRIS belum dapat dikirim.')
        return body['result']

    async def close(self):
        await self.session.close()


async def authenticate(api_id, api_hash, token):
    """Validate each deployment's app credentials without writing session files."""
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    if type(api_id) is not int or api_id <= 0 or not re.fullmatch(r'[0-9a-fA-F]{32}', api_hash):
        raise ValueError('API ID harus positif dan API hash harus 32 karakter heksadesimal.')
    if not TOKEN.fullmatch(token):
        raise ValueError('Format token tidak valid.')
    client = TelegramClient(StringSession(), api_id, api_hash, receive_updates=False,
                            connection_retries=1, request_retries=1)
    try:
        async with asyncio.timeout(60):
            await client.start(bot_token=token)
            me = await client.get_me()
            if not me.bot or not me.username:
                raise ValueError('Token harus milik bot Telegram.')
            return {'id': me.id, 'username': me.username, 'name': ' '.join(n for n in (me.first_name, me.last_name) if n)}, client.session.save()
    except asyncio.CancelledError:
        raise
    except Exception:
        raise ValueError('Login Telegram gagal. Periksa API ID, API hash, token, dan koneksi server.') from None
    finally:
        await client.disconnect()


class Poller:
    def __init__(self, api, handler, is_enabled=lambda: True):
        self.api, self.handler, self.is_enabled = api, handler, is_enabled
        self.task = None
        self.work = set()
        self.user_locks = {}
        self.slots = asyncio.Semaphore(32)

    async def start(self):
        await self.api.call('deleteWebhook', drop_pending_updates=False)
        self.task = asyncio.create_task(self.run())

    async def dispatch(self, update):
        subject = update.get('message') or update.get('callback_query') or {}
        user = subject.get('from', {}).get('id', 0)
        lock = self.user_locks.setdefault(user, asyncio.Lock())
        async with lock:
            if self.is_enabled():
                try:
                    await self.handler(update)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    # Exception messages may contain request payloads; log type only.
                    log.warning('Handler failed: %s', type(exc).__name__)

    async def run(self):
        offset = 0
        while True:
            try:
                updates = await self.api.call('getUpdates', offset=offset, timeout=50,
                    allowed_updates=['message', 'callback_query', 'chat_member'])
                for update in updates:
                    await self.slots.acquire()
                    task = asyncio.create_task(self.dispatch(update))
                    self.work.add(task)
                    task.add_done_callback(self.work.discard)
                    task.add_done_callback(lambda _: self.slots.release())
                    offset = update['update_id'] + 1
            except asyncio.CancelledError:
                raise
            except TelegramFailure as exc:
                log.warning('Polling failed (code %s)', exc.code)
                await asyncio.sleep(exc.retry_after or 5)

    async def stop(self):
        tasks = ([self.task] if self.task else []) + list(self.work)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        ui = getattr(self.handler, '__self__', None)
        if ui is not None and hasattr(ui, 'close'):
            await ui.close()
        await self.api.close()
