import unittest
from unittest.mock import AsyncMock
from test_payment_integration import DummyProvider
import test_payment_integration as fixtures
from subgate.saweria import confirmed_receipt

class SimplePaymentTests(unittest.IsolatedAsyncioTestCase):
    setUp=fixtures.PaymentIntegrationTests.setUp
    asyncTearDown=fixtures.PaymentIntegrationTests.asyncTearDown
    cb=fixtures.PaymentIntegrationTests.cb
    msg=fixtures.PaymentIntegrationTests.msg

    async def test_username_alone_saves_and_checkout_without_public_url(self):
        self.ui.public_base=''
        self.db.conn.execute('DELETE FROM payment_accounts WHERE owner=2'); self.db.conn.commit()
        await self.cb(2,'p:account')
        await self.ui.handle(self.msg(2,'example'))
        self.assertTrue(self.p.account(2)['enabled'])
        self.assertEqual(self.p.account(2)['key'],'')
        self.assertIsNone(self.ui.state(2))
        self.ui.provider.create=AsyncMock(return_value={'transaction_id':'simple','qr':'000201','total':1000})
        self.api.send_photo_bytes=AsyncMock(return_value={'message_id':1})
        await self.cb(3,f'p:buy:{self.pkg}')
        self.assertIsNone(self.ui.state(3))
        self.api.send_photo_bytes.assert_awaited_once()

    async def test_success_receipt_without_webhook(self):
        order=self.p.new_order(99,3,self.pkg)
        self.p.attach(order['id'],'tx1','000201',1000)
        provider=self.ui.provider
        provider.check=AsyncMock(return_value={'id':'tx1','username':'example','amount_raw':1000,'transaction_status':'SUCCESS'})
        self.assertEqual(await self.ui.service.check(order['id'],3),'verified')
        self.assertEqual(self.p.order(99,order['id'])['payment'],'verified')
        self.assertEqual(self.p.order(99,order['id'])['delivered'],1)

    async def test_pending_expired_unknown_mismatch_never_deliver(self):
        for index,fields in enumerate(({}, {'transaction_status':'Pending'}, {'transaction_status':'Expired'},
            {'transaction_status':'SUCCESS','username':'someone'}, {'transaction_status':'SUCCESS','amount_raw':999},
            {'transaction_status':'SUCCESS','id':'wrong'})):
            order=self.p.new_order(99,3,self.pkg)
            transaction='tx'+str(index)
            self.p.attach(order['id'],transaction,'000201',1000)
            body={'id':transaction,'username':'example','amount_raw':1000,'qr_string':''}|fields
            self.ui.provider.check=AsyncMock(return_value=body)
            await self.ui.service.check(order['id'],3)
            self.assertEqual(self.p.order(99,order['id'])['payment'],'pending')
        self.assertFalse(any(m=='createChatInviteLink' for m,a in self.api.calls))

    async def test_cancelled_receipt_is_late(self):
        order=self.p.new_order(99,3,self.pkg)
        self.p.attach(order['id'],'tx1','000201',1000)
        self.p.cancel(99,3,order['id'])
        self.ui.provider.check=AsyncMock(return_value={'id':'tx1','username':'example','amount_raw':1000,'transaction_status':'SUCCESS'})
        self.assertEqual(await self.ui.service.check(order['id'],3),'late')
        self.assertFalse(any(m=='createChatInviteLink' for m,a in self.api.calls))

    async def test_receipt_validator_requires_explicit_success_and_exact_data(self):
        self.assertTrue(confirmed_receipt({'id':'tx','username':'example','amount_raw':1000,'transaction_status':'SUCCESS'},'tx','example',1000))
        self.assertFalse(confirmed_receipt({'id':'tx','username':'example','amount_raw':True,'transaction_status':'SUCCESS'},'tx','example',1))
