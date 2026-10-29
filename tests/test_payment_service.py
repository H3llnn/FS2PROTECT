import asyncio
import unittest
import test_payment_store as fixtures
from subgate.payment_service import PaymentService
from subgate.service import TelegramFailure

class FakePayAPI:
    def __init__(self): self.calls=[]; self.fail_send=False
    async def call(self,method,**kw):
        self.calls.append((method,kw))
        if method=='getChat': return {'type':'channel','title':'VIP'}
        if method=='getChatMember': return {'status':'administrator','can_invite_users':True}
        if method=='createChatInviteLink': return {'invite_link':'https://t.me/+one'}
        if method=='sendMessage' and kw['chat_id']==3 and self.fail_send: raise TelegramFailure(503,'temporary')
        return {'message_id':1}

class PaymentServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        fixtures.PaymentStoreTests.setUp(self)
        self.api=FakePayAPI()
        self.service=PaymentService(self.db,99,self.api,None)
    def tearDown(self): fixtures.PaymentStoreTests.tearDown(self)
    def paid(self):
        o=self.p.new_order(99,3,self.pkg)
        self.p.attach(o['id'],'tx1','000201',1000)
        self.p.accept(2,'tx1',1000)
        return o['id']
    async def test_concurrent_fulfillment_one_invite(self):
        ident=self.paid()
        await asyncio.gather(self.service.fulfill(ident),self.service.fulfill(ident))
        self.assertEqual(sum(m=='createChatInviteLink' for m,a in self.api.calls),1)
        self.assertEqual(self.p.order(99,ident)['delivered'],1)
    async def test_send_retry_reuses_invite(self):
        ident=self.paid(); self.api.fail_send=True
        await self.service.fulfill(ident)
        self.assertEqual(self.p.order(99,ident)['delivered'],0)
        self.api.fail_send=False
        await self.service.fulfill(ident)
        self.assertEqual(sum(m=='createChatInviteLink' for m,a in self.api.calls),1)
        self.assertEqual(self.p.order(99,ident)['delivered'],1)
    async def test_join_consumes_and_revokes(self):
        ident=self.paid(); await self.service.fulfill(ident)
        await self.service.join({'chat':{'id':-1001},'old_chat_member':{'status':'left'},'new_chat_member':{'status':'member'},'invite_link':{'invite_link':'https://t.me/+one'}})
        self.assertEqual(self.p.order(99,ident)['used'],1)
        self.assertEqual(self.p.order(99,ident)['revoked'],1)
    async def test_cancelled_payment_never_delivered(self):
        o=self.p.new_order(99,3,self.pkg); self.p.attach(o['id'],'tx1','000201',1000)
        self.p.cancel(99,3,o['id']); self.p.accept(2,'tx1',1000)
        await self.service.fulfill(o['id'])
        self.assertFalse(any(m=='createChatInviteLink' for m,a in self.api.calls))
    async def test_unknown_creation_does_not_create_second_invite(self):
        ident=self.paid(); self.p.update(99,ident,delivery='creating')
        await self.service.fulfill(ident)
        self.assertFalse(any(m=='createChatInviteLink' for m,a in self.api.calls))

    async def test_target_failure_notifies_owner_and_other_orders_not_starved(self):
        ident=self.paid()
        original=self.api.call
        async def broken(method,**kw):
            if method=='getChatMember': return {'status':'left'}
            return await original(method,**kw)
        self.api.call=broken
        await self.service.tick()
        self.assertTrue(any(m=='sendMessage' and a['chat_id']==2 for m,a in self.api.calls))
        self.assertGreater(self.p.order(99,ident)['work_due'],0)
        self.assertFalse(any(m=='createChatInviteLink' for m,a in self.api.calls))
        self.assertEqual(self.p.work(99),[])
        self.api.call=original
        other=self.p.new_order(99,4,self.pkg)
        self.p.attach(other['id'],'tx2','000201',1000); self.p.accept(2,'tx2',1000)
        await self.service.tick()
        self.assertTrue(self.p.order(99,other['id'])['delivered'])
