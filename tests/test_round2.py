import asyncio
import unittest
from unittest.mock import AsyncMock
import test_payment_integration as fixtures

class RoundTwoTests(unittest.IsolatedAsyncioTestCase):
    setUp=fixtures.PaymentIntegrationTests.setUp
    asyncTearDown=fixtures.PaymentIntegrationTests.asyncTearDown
    cb=fixtures.PaymentIntegrationTests.cb
    def latest(self): return next(a for m,a in reversed(self.api.calls) if m=='sendMessage')
    def paid(self):
        o=self.p.new_order(99,3,self.pkg)
        self.p.attach(o['id'],'retry-tx','000201',1000)
        self.p.accept(2,'retry-tx',1000)
        return o['id']
    async def test_retry_reuses_invite_and_is_single_delivery(self):
        ident=self.paid(); self.api.fail_send=True
        await self.ui.service.fulfill(ident)
        self.api.fail_send=False
        await self.cb(3,'p:access:'+ident)
        self.assertIn('Coba Kirim Link Lagi',str(self.latest()['reply_markup']))
        await asyncio.gather(self.cb(3,'p:retry:'+ident),self.cb(3,'p:retry:'+ident))
        self.assertEqual(sum(m=='createChatInviteLink' for m,a in self.api.calls),1)
        self.assertEqual(self.p.order(99,ident)['delivered'],1)
        self.assertNotIn('Coba Kirim Link Lagi',str(self.latest()['reply_markup']))
        sends=sum(m=='sendMessage' and a['chat_id']==3 and 'Pembayaran berhasil!' in a['text'] for m,a in self.api.calls)
        self.assertEqual(sends,2) # one failed send, one successful retry
    async def test_retry_rejects_other_buyer_unpaid_and_used(self):
        ident=self.paid()
        await self.cb(4,'p:retry:'+ident)
        self.assertFalse(any(m=='createChatInviteLink' for m,a in self.api.calls))
        self.p.update(99,ident,used=1)
        await self.cb(3,'p:retry:'+ident)
        self.assertNotIn('Coba Kirim Link Lagi',str(self.latest()['reply_markup']))
        pending=self.p.new_order(99,3,self.pkg)
        await self.cb(3,'p:retry:'+pending['id'])
        self.assertFalse(any(m=='createChatInviteLink' for m,a in self.api.calls))
    async def test_uncertain_invite_retry_never_creates_another(self):
        ident=self.paid(); self.p.update(99,ident,delivery='uncertain')
        await self.cb(3,'p:retry:'+ident)
        self.assertFalse(any(m=='createChatInviteLink' for m,a in self.api.calls))
    async def test_owner_menu_and_buyer_copy(self):
        await self.cb(2,'p:settings')
        self.assertNotIn('Transaksi',str(self.latest()['reply_markup']))
        self.assertIn('Saweria',str(self.latest()['reply_markup']))
        await self.cb(3,'p:list:0')
        self.assertIn('Pilih yang kamu suka',self.latest()['text'])
        await self.cb(3,'p:history:0')
        self.assertIn('Belum ada koleksi',self.latest()['text'])
        await self.cb(3,f'p:package:{self.pkg}:0')
        self.assertNotIn('saweria',self.latest()['text'].lower())
        self.assertIn('Sekali beli',self.latest()['text'])
    async def test_provider_errors_do_not_leak_to_buyer(self):
        for error in ('Saweria HTTP 400','Koneksi Saweria bermasalah.','Status Saweria belum dapat dipastikan.'):
            self.assertNotIn('saweria',self.ui.error_text(ValueError(error)).lower())
        self.ui.provider.create=AsyncMock(side_effect=ValueError('Saweria HTTP 400'))
        await self.cb(3,f'p:buy:{self.pkg}')
        buyer=[a['text'] for m,a in self.api.calls if m=='sendMessage' and a['chat_id']==3]
        self.assertTrue(buyer)
        self.assertTrue(all('saweria' not in t.lower() for t in buyer))
