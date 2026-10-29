import hashlib
import hmac
import json
import unittest
import test_payment_store as fixtures
from aiohttp.test_utils import make_mocked_request
from subgate.payment_webhook import PaymentWebhook
from subgate.payment_ui import PaymentUI
from test_payment_service import FakePayAPI

class DummyProvider:
    async def recipient(self,username): return 'recipient'
    async def check(self,transaction): return 'unknown'

class Request:
    def __init__(self,route,body,key='secret-key',bad=False):
        self.match_info={'route':route}; self.body=body
        msg=''.join(str(body[k]) for k in ('version','id','amount_raw','donator_name','donator_email')).encode()
        self.headers={'Saweria-Callback-Signature':'bad' if bad else hmac.new(key.encode(),msg,hashlib.sha256).hexdigest()}
    async def json(self): return self.body

class PaymentIntegrationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        fixtures.PaymentStoreTests.setUp(self)
        self.api=FakePayAPI()
        self.ui=PaymentUI(self.db,99,self.api,'https://test.invalid',DummyProvider())
    async def asyncTearDown(self):
        await self.ui.close()
        fixtures.PaymentStoreTests.tearDown(self)
    def msg(self,user,text):
        return {'message':{'message_id':1,'from':{'id':user,'first_name':'A'},'chat':{'id':user,'type':'private'},'text':text}}
    async def cb(self,user,data):
        await self.ui.handle({'callback_query':{'id':'x','from':{'id':user},'data':data,'message':{'chat':{'id':user,'type':'private'}}}})
    async def test_callback_before_attach_and_replay(self):
        o=self.p.new_order(99,3,self.pkg)
        body=dict(version='2022.01',id='tx1',amount_raw=1000,donator_name='A',donator_email='a@b.c')
        endpoint=PaymentWebhook(self.db,None)
        route=self.p.account(2)['route']
        await endpoint.receive(Request(route,body))
        self.p.attach(o['id'],'tx1','000201',1000)
        self.assertEqual(self.p.order(99,o['id'])['payment'],'verified')
        await endpoint.receive(Request(route,body))
        self.assertEqual(len(self.p.history(99,3)),1)
    async def test_bad_signature_cannot_pay(self):
        from aiohttp import web
        o=self.p.new_order(99,3,self.pkg); self.p.attach(o['id'],'tx1','000201',1000)
        body=dict(version='2022.01',id='tx1',amount_raw=1000,donator_name='A',donator_email='a@b.c')
        with self.assertRaises(web.HTTPForbidden):
            await PaymentWebhook(self.db,None).receive(Request(self.p.account(2)['route'],body,bad=True))
        self.assertEqual(self.p.order(99,o['id'])['payment'],'pending')
    async def test_owner_only_settings_and_package_edit(self):
        await self.cb(3,'p:settings')
        self.assertNotIn(3,self.ui.pending)
        await self.cb(3,f'p:edit:{self.pkg}:price')
        self.assertEqual(self.p.package(99,self.pkg)['price'],1000)
    async def test_catalog_names_only_and_history_success_only(self):
        await self.cb(3,'p:list:0')
        labels=str(self.api.calls[-1][1]['reply_markup'])
        self.assertIn('VIP',labels); self.assertNotIn('1000',labels)
        o=self.p.new_order(99,3,self.pkg)
        await self.cb(3,'p:history:0')
        self.assertNotIn(o['id'],str(self.api.calls[-1]))
    async def test_direct_checkout_cancel_pending_order(self):
        from unittest.mock import AsyncMock
        self.ui.provider.create=AsyncMock(return_value={'transaction_id':'cancelme','qr':'000201','total':1000})
        self.api.send_photo_bytes=AsyncMock(return_value={'message_id':1})
        await self.cb(3,f'p:buy:{self.pkg}')
        ident=self.db.rows('SELECT id FROM payment_orders')[0]['id']
        self.assertIsNone(self.ui.state(3))
        await self.cb(3,'p:cancel:'+ident)
        self.assertEqual(self.p.order(99,ident)['state'],'cancelled')
    async def test_package_deletion_requires_owner_confirmation(self):
        await self.cb(2,f'p:status:{self.pkg}:deleted')
        self.assertEqual(self.p.package(99,self.pkg)['status'],'active')
        await self.cb(2,f'p:ask:{self.pkg}:deleted')
        await self.cb(2,f'p:status:{self.pkg}:deleted')
        self.assertEqual(self.p.package(99,self.pkg)['status'],'deleted')

    async def test_dynamic_titles_escaped(self):
        self.p.save_package(99,2,self.pkg,name='VIP <3 & Friends')
        await self.cb(3,f'p:package:{self.pkg}:0')
        text=next(args['text'] for method,args in reversed(self.api.calls) if method=='sendMessage')
        self.assertIn('VIP &lt;3 &amp; Friends',text)
        self.db.display_name(99,'Bot <3')
        await self.cb(3,'p:home')
        self.assertIn('Bot &lt;3',next(args['text'] for method,args in reversed(self.api.calls) if method=='sendMessage'))

    async def test_financial_detail_only_child_owner(self):
        order=self.p.new_order(99,3,self.pkg)
        await self.cb(4,'p:order:'+order['id'])
        self.assertNotIn(order['id'],str(self.api.calls[-1]))
        await self.cb(2,'p:order:'+order['id'])
        self.assertIn(order['id'],str(self.api.calls[-1]))
