import asyncio
import io
import unittest
from unittest.mock import AsyncMock
from PIL import Image
import test_payment_store as fixtures
import test_payment_integration as integration

class PaymentQRTests(unittest.IsolatedAsyncioTestCase):
    setUp=integration.PaymentIntegrationTests.setUp
    asyncTearDown=integration.PaymentIntegrationTests.asyncTearDown
    cb=integration.PaymentIntegrationTests.cb
    msg=integration.PaymentIntegrationTests.msg
    async def test_checkout_sends_png_then_signature_delivers(self):
        self.ui.provider.create=AsyncMock(return_value={'transaction_id':'txpng','qr':'000201','total':1000})
        self.api.send_photo_bytes=AsyncMock(return_value={'message_id':1})
        await self.cb(3,f'p:buy:{self.pkg}')
        args=self.api.send_photo_bytes.call_args.args
        self.assertEqual(Image.open(io.BytesIO(args[1])).format,'PNG')
        rows=self.db.rows('SELECT id,payment FROM payment_orders')
        self.assertEqual(rows[0]['payment'],'pending')
        self.assertFalse(any(m=='createChatInviteLink' for m,a in self.api.calls))
        self.p.accept(2,'txpng',1000)
        await self.ui.service.tick()
        self.assertTrue(self.p.order(99,rows[0]['id'])['delivered'])
