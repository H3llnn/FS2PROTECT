import io
import unittest
from unittest.mock import AsyncMock
from PIL import Image
import test_payment_integration as fixtures

class DirectCheckoutTests(unittest.IsolatedAsyncioTestCase):
    setUp=fixtures.PaymentIntegrationTests.setUp
    asyncTearDown=fixtures.PaymentIntegrationTests.asyncTearDown
    cb=fixtures.PaymentIntegrationTests.cb
    msg=fixtures.PaymentIntegrationTests.msg

    async def test_buy_directly_sends_qr_no_email_no_extra_confirmation(self):
        self.ui.provider.create=AsyncMock(return_value={'transaction_id':'direct','qr':'000201','total':1000})
        self.api.send_photo_bytes=AsyncMock(return_value={'message_id':1})
        await self.cb(3,f'p:buy:{self.pkg}')
        self.api.send_photo_bytes.assert_awaited_once()
        args=self.api.send_photo_bytes.call_args.args
        self.assertEqual(Image.open(io.BytesIO(args[1])).format,'PNG')
        self.assertIsNone(self.ui.state(3))
        self.assertEqual(self.ui.provider.create.call_args.args[3],None)

    async def test_double_click_reuses_pending_qr(self):
        self.ui.provider.create=AsyncMock(return_value={'transaction_id':'direct','qr':'000201','total':1000})
        self.api.send_photo_bytes=AsyncMock(return_value={'message_id':1})
        await self.cb(3,f'p:buy:{self.pkg}')
        await self.cb(3,f'p:buy:{self.pkg}')
        self.ui.provider.create.assert_awaited_once()
        self.assertEqual(len(self.db.rows('SELECT id FROM payment_orders')),1)

    async def test_provider_omits_email_in_payload(self):
        import binascii,json
        from subgate.saweria import Saweria
        client=Saweria(None)
        raw='0002015303360540410006304'
        qr=raw+format(binascii.crc_hqx(raw.encode(),0xffff),'04X')
        client.request=AsyncMock(return_value=json.dumps({'data':{'id':'12345678-1234-1234-1234-123456789abc','qr_string':qr}}))
        await client.create({'recipient':'recipient'},1000,'Buyer',None,'order')
        payload=client.request.call_args.args[1]
        self.assertNotIn('email',payload['customer_info'])
