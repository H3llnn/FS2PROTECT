"""Process entry point and configuration; one process per persistent data volume."""
import asyncio
import logging
import os
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from cryptography.fernet import Fernet

from .telegram import API, Poller, TOKEN
from .store import Store
from .runtime import Manager
from .ui import MasterUI


@dataclass(frozen=True)
class Config:
    token: str
    owner: int
    key: bytes
    data: Path

    @classmethod
    def read(cls, env):
        try:
            owner = int(env.get('MASTER_OWNER_ID', ''))
            token = env.get('MASTER_BOT_TOKEN', '')
            key = env.get('SECRET_KEY', '').encode()
            if owner <= 0 or not TOKEN.fullmatch(token):
                raise ValueError
            Fernet(key)
        except (ValueError, TypeError):
            raise ValueError('Isi MASTER_OWNER_ID, MASTER_BOT_TOKEN, dan SECRET_KEY yang valid dalam config.env.') from None
        return cls(token, owner, key, Path(env.get('DATA_DIR') or './data').resolve())


@contextmanager
def instance_lock(directory):
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / '.instance.lock').open('a+b') as handle:
        handle.seek(0)
        handle.write(b'0')
        handle.flush()
        handle.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise RuntimeError('Instance SubGate lain sudah memakai DATA_DIR ini.') from None
        try:
            yield
        finally:
            if os.name == 'nt':
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


async def main():
    from dotenv import load_dotenv
    load_dotenv('config.env')
    config = Config.read(os.environ)
    # Telegram/HTTP debug logging may expose credentials in request URLs.
    logging.basicConfig(level=logging.WARNING, format='%(levelname)s %(name)s: %(message)s')
    for name in ('telethon', 'aiohttp', 'asyncio'):
        logging.getLogger(name).setLevel(logging.ERROR)
    with instance_lock(config.data):
        db = Store(config.data / 'subgate.sqlite', config.key, config.owner)
        api = API(config.token)
        manager = poller = None
        try:
            me = await api.call('getMe')
            manager = Manager(db, me['id'])
            ui = MasterUI(db, api, manager)
            poller = Poller(api, ui.handle)
            await poller.start()
            await manager.restore()
            manager.maintenance_task = asyncio.create_task(manager.maintenance())
            print(f"Zeisss SubGate aktif: @{me['username']}", flush=True)
            await asyncio.Future()
        finally:
            if poller:
                await poller.stop()
            else:
                await api.close()
            if manager:
                await manager.close()
            db.close()
