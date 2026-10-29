"""Track only transient bot screens, never content deliveries."""
import logging
from .service import TelegramFailure

log = logging.getLogger(__name__)

class Display:
    def __init__(self, conn, api):
        self.conn, self.api = conn, api
        with conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS display_screens (
                bot INTEGER NOT NULL, chat INTEGER NOT NULL, message_id INTEGER NOT NULL,
                PRIMARY KEY(bot, chat, message_id))""")

    async def replace(self, bot, chat, messages):
        previous = self.conn.execute(
            'SELECT message_id FROM display_screens WHERE bot=? AND chat=?', (bot, chat)).fetchall()
        with self.conn:
            self.conn.execute('DELETE FROM display_screens WHERE bot=? AND chat=?', (bot, chat))
            self.conn.executemany('INSERT INTO display_screens VALUES (?,?,?)',
                [(bot, chat, message['message_id']) for message in messages])
        for row in previous:
            try:
                await self.api.call('deleteMessage', chat_id=chat, message_id=row[0])
            except TelegramFailure:
                log.warning('Unable to delete previous UI screen; removing its keyboard')
                try:
                    await self.api.call('editMessageReplyMarkup', chat_id=chat, message_id=row[0],
                                        reply_markup={'inline_keyboard': []})
                except TelegramFailure:
                    log.warning('Unable to remove previous UI keyboard')
