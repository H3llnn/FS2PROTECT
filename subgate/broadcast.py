"""Private broadcasts with actor-bound, single-use confirmations."""
import asyncio
import secrets
import time
from .service import inline, action


class Broadcast:
    def __init__(self, db, bot, api, is_allowed, show=None, interval=.05, track_preview=None):
        self.db, self.bot, self.api, self.is_allowed = db, bot, api, is_allowed
        self.show = show or self._show
        self.interval = interval
        self.track_preview=track_preview
        self.previews, self.jobs = {}, {}
        self.closed = False

    async def _show(self, actor, text, buttons):
        return await self.api.call('sendMessage', chat_id=actor, text=text,
                                   parse_mode='HTML', reply_markup=inline(buttons))

    def cancel(self, actor):
        self.previews.pop(actor, None)

    def _authorize(self, actor):
        if self.closed or not self.is_allowed(actor):
            raise PermissionError('Broadcast tidak diizinkan.')

    async def preview(self, actor, source_message_id):
        self._authorize(actor)
        if actor in self.jobs:
            raise ValueError('Broadcast masih berjalan.')
        self.cancel(actor)
        preview_message=await self.api.call('copyMessage', chat_id=actor, from_chat_id=actor,
                            message_id=source_message_id)
        nonce = secrets.token_hex(12)
        state = dict(nonce=nonce, source=source_message_id, expires=time.monotonic() + 600)
        self.previews[actor] = state
        try:
            await self.show(actor, '📢 Preview Broadcast\nPesan di atas akan dikirim ke pengguna bot. Siap mengirimnya?',
                            [[action('📨 Kirim Broadcast', f'bc:send:{nonce}')],
                             [action('✖️ Batalkan', 'x:cancel')]])
        except BaseException:
            if self.previews.get(actor) is state:
                self.cancel(actor)
            raise
        if self.track_preview: await self.track_preview(actor,preview_message)
        return nonce

    async def start(self, actor, nonce):
        self._authorize(actor)
        state = self.previews.get(actor)
        if (actor in self.jobs or not state or state['nonce'] != nonce
                or state['expires'] <= time.monotonic()):
            raise ValueError('Konfirmasi broadcast tidak berlaku.')
        self.cancel(actor)
        job = dict(creator=actor, nonce=nonce, source=state['source'],
                   recipients=tuple(self.db.users(self.bot)), sent=0, failed=0, stopped=False)
        self.jobs[actor] = job
        task = asyncio.create_task(self._run(job))
        job['task'] = task
        return task

    async def stop(self, actor, nonce):
        job = self.jobs.get(actor)
        if not job or job['creator'] != actor or job['nonce'] != nonce:
            return False
        job['stopped'] = True
        return True

    async def _run(self, job):
        actor = job['creator']
        try:
            progress=await self.show(actor, '📢 Broadcast sedang dikirim…',
                            [[action('⏹ Hentikan Broadcast', f"bc:stop:{job['nonce']}")]])
            for recipient in job['recipients']:
                if job['stopped'] or not self.is_allowed(actor):
                    job['stopped'] = True
                    break
                try:
                    await self.api.call('copyMessage', chat_id=recipient,
                                        from_chat_id=actor, message_id=job['source'])
                except asyncio.CancelledError:
                    raise
                except Exception:
                    job['failed'] += 1
                else:
                    job['sent'] += 1
                await asyncio.sleep(self.interval)
        except asyncio.CancelledError:
            job['stopped'] = True
        except Exception:
            job['stopped'] = True
        finally:
            remaining = len(job['recipients']) - job['sent'] - job['failed']
            if job['stopped']:
                text = (f"⏹ Broadcast dihentikan\n\n📨 Terkirim: {job['sent']}"
                        f"\n⚠️ Gagal: {job['failed']}\n⏳ Belum dikirim: {remaining}")
            else:
                text = (f"✅ Broadcast selesai\n\n📨 Terkirim: {job['sent']}"
                        f"\n⚠️ Gagal: {job['failed']}")
            try:
                await self.api.call('sendMessage', chat_id=actor, text=text)
                if isinstance(locals().get('progress'),dict) and 'message_id' in progress:
                    try: await self.api.call('deleteMessage',chat_id=actor,message_id=progress['message_id'])
                    except Exception: pass
            except Exception:
                pass
            finally:
                if self.jobs.get(actor) is job:
                    self.jobs.pop(actor, None)

    async def close(self):
        self.closed = True
        self.previews.clear()
        tasks = [job['task'] for job in self.jobs.values()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self.jobs.clear()
