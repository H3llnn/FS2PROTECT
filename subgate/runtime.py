"""Lifecycle coordination. A shared lock serializes deploy, revoke and toggles."""
import asyncio
import logging
import time

from .service import Delivery, TelegramFailure

log = logging.getLogger(__name__)


class Manager:
    def __init__(self, db, master_bot_id, authenticate=None, runner_factory=None):
        self.db, self.master_bot_id = db, master_bot_id
        if authenticate is None:
            from .telegram import authenticate
        self.authenticate = authenticate
        self.runner_factory = runner_factory or self.make_runner
        self.running = {}
        self.lock = asyncio.Lock()
        self.maintenance_task = None

    def make_runner(self, record, credentials):
        from .telegram import API, Poller
        from .ui import ChildUI
        api = API(credentials['token'])
        ui = ChildUI(self.db, record['id'], api)
        return Poller(api, ui.handle, lambda: bool(self.db.bot(record['id'])['active'])
                      and self.db.allowed(record['owner']))

    async def lookup_name(self, bot):
        from .telegram import API
        runner = self.running.get(bot)
        api = runner.api if runner else API(self.db.credentials(bot)['token'])
        try:
            me = await api.call('getMe')
            return ' '.join(v for v in (me.get('first_name'), me.get('last_name')) if v)
        finally:
            if not runner:
                await api.close()

    async def _start(self, bot):
        if bot in self.running:
            return
        record = self.db.bot(bot)
        runner = self.runner_factory(record, self.db.credentials(bot))
        try:
            if hasattr(runner, 'start'):
                await runner.start()
        except BaseException:
            await runner.stop()
            raise
        self.running[bot] = runner

    async def deploy(self, owner, api_id, api_hash, token):
        if not self.db.allowed(owner):
            raise PermissionError('Kamu belum mendapat izin membuat bot.')
        me, session = await self.authenticate(api_id, api_hash, token)
        bot = me['id']
        if bot == self.master_bot_id:
            raise ValueError('Token bot induk tidak boleh didaftarkan sebagai bot anak.')
        async with self.lock:
            if not self.db.allowed(owner):
                raise PermissionError('Izin kamu sudah dicabut.')
            existing = self.db.rows('SELECT owner FROM bots WHERE id=?', (bot,))
            if existing and existing[0]['owner'] != owner:
                raise PermissionError('Bot sudah terdaftar milik pengguna lain.')
            if bot in self.running:
                await self.running.pop(bot).stop()
            self.db.deploy(owner, bot, me['username'], api_id, api_hash, token, session, name=me.get('name'))
            try:
                await self._start(bot)
            except Exception:
                self.db.set_active(self.db.master_owner, bot, False)
                raise ValueError('Bot tersimpan tetapi belum dapat aktif. Coba deploy lagi.') from None
        return me

    async def revoke(self, actor, owner):
        async with self.lock:
            self.db.revoke(actor, owner)
            for record in self.db.bots(owner):
                runner = self.running.pop(record['id'], None)
                if runner:
                    await runner.stop()

    async def toggle(self, actor, bot, active):
        async with self.lock:
            self.db.set_active(actor, bot, active)
            if active:
                try:
                    await self._start(bot)
                except Exception:
                    self.db.set_active(actor, bot, False)
                    raise ValueError('Bot belum dapat aktif. Pemilik perlu memeriksa token/deploy ulang.') from None
            else:
                runner = self.running.pop(bot, None)
                if runner:
                    await runner.stop()

    async def restore(self):
        async with self.lock:
            for record in self.db.bots():
                if record['active'] and self.db.allowed(record['owner']):
                    try:
                        await self._start(record['id'])
                    except Exception as exc:
                        log.warning('Restore bot %s failed: %s', record['id'], type(exc).__name__)

    async def maintenance(self):
        from .telegram import API
        tick = 0
        while True:
            if tick % 6 == 0:
                await self.restore()
            for record in self.db.bots():
                api = None
                temporary = False
                try:
                    runner = self.running.get(record['id'])
                    if runner:
                        api = runner.api
                    elif self.db.due(time.time(), record['id']):
                        # Stopped bots still clean up already scheduled messages, without polling.
                        api = API(self.db.credentials(record['id'])['token'])
                        temporary = True
                    if api is None:
                        continue
                    delivery = Delivery(self.db, record['id'], api)
                    await delivery.expire()
                    if tick % 6 == 0 and runner:
                        scopes = [i['scope'] for i in self.db.incidents() if i['bot'] == record['id']]
                        for scope in scopes:
                            if scope.startswith('chat:'):
                                try:
                                    await delivery.check_admin(int(scope.split(':')[1]))
                                    await delivery.incident(scope, False)
                                except TelegramFailure:
                                    pass
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    log.warning('Maintenance bot %s failed: %s', record['id'], type(exc).__name__)
                finally:
                    if temporary and api:
                        await api.close()
            tick += 1
            await asyncio.sleep(10)

    async def close(self):
        if self.maintenance_task:
            self.maintenance_task.cancel()
            await asyncio.gather(self.maintenance_task, return_exceptions=True)
        for runner in list(self.running.values()):
            await runner.stop()
        self.running.clear()
