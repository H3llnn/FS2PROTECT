import unittest
import test_payment_integration as fixtures
from subgate.service import TelegramFailure

class PolishUITests(unittest.IsolatedAsyncioTestCase):
    setUp=fixtures.PaymentIntegrationTests.setUp
    asyncTearDown=fixtures.PaymentIntegrationTests.asyncTearDown
    cb=fixtures.PaymentIntegrationTests.cb
    msg=fixtures.PaymentIntegrationTests.msg
    def latest(self): return next(a for m,a in reversed(self.api.calls) if m=='sendMessage')

    async def test_admin_requires_start_and_notification_success(self):
        await self.cb(2,'p:add_admin'); await self.ui.handle(self.msg(2,'4'))
        self.assertNotIn(4,self.db.admins(99))
        self.assertIn('Izin admin belum diberikan',self.latest()['text'])
        await self.ui.handle(self.msg(4,'/start'))
        original=self.api.call
        async def blocked(method,**kw):
            if method=='sendMessage' and kw['chat_id']==4: raise TelegramFailure(403,'blocked')
            return await original(method,**kw)
        self.api.call=blocked
        await self.cb(2,'p:add_admin'); await self.ui.handle(self.msg(2,'4'))
        self.assertNotIn(4,self.db.admins(99))
        self.api.call=original
        await self.cb(2,'p:add_admin'); await self.ui.handle(self.msg(2,'4'))
        self.assertIn(4,self.db.admins(99))
        self.assertTrue(any(m=='sendMessage' and a['chat_id']==4 and 'Kamu sekarang admin' in a['text'] for m,a in self.api.calls))

    async def test_role_menus_and_forged_owner_callbacks(self):
        self.db.admin(99,2,4,True)
        await self.cb(4,'p:settings')
        labels=str(self.latest()['reply_markup'])
        self.assertIn('Broadcast',labels); self.assertNotIn('Transaksi',labels); self.assertNotIn('Saweria',labels)
        for data in ('p:orders:0','p:sort:0','p:add_admin','p:account',f'p:edit:{self.pkg}:price',f'p:ask:{self.pkg}:inactive'):
            await self.cb(4,data)
            self.assertIn('Akses terbatas',self.latest()['text'])
        await self.cb(3,'p:settings')
        self.assertIn('Akses terbatas',self.latest()['text'])

    async def test_welcome_preview_then_commit_rechecks_role(self):
        self.db.admin(99,2,4,True)
        original=self.db.settings(99)['payment_welcome']
        await self.cb(4,'p:welcome'); await self.ui.handle(self.msg(4,'Halo semua'))
        self.assertEqual(self.db.settings(99)['payment_welcome'],original)
        self.assertIn('Preview',self.latest()['text'])
        self.db.admin(99,2,4,False)
        await self.cb(4,'p:save_welcome')
        self.assertEqual(self.db.settings(99)['payment_welcome'],original)
        self.db.admin(99,2,4,True)
        await self.cb(4,'p:welcome'); await self.ui.handle(self.msg(4,'Halo semua')); await self.cb(4,'p:save_welcome')
        self.assertEqual(self.db.settings(99)['payment_welcome'],'Halo semua')

    async def test_minimum_price_keeps_form(self):
        await self.cb(2,f'p:edit:{self.pkg}:price')
        await self.ui.handle(self.msg(2,'500'))
        self.assertEqual(self.p.package(99,self.pkg)['price'],1000)
        self.assertIn('Harga minimal Rp1.000',self.latest()['text'])
        self.assertEqual(self.ui.state(2)['kind'],'edit_package')

    async def test_active_qr_survives_menu_cancel_only_clears_own(self):
        one=self.p.new_order(99,3,self.pkg); two=self.p.new_order(99,3,self.pkg)
        self.p.attach(one['id'],'qr1','000201',1000); self.p.attach(two['id'],'qr2','000201',1000)
        self.p.qr_message(99,one['id'],3,701); self.p.qr_message(99,two['id'],3,702)
        await self.cb(3,'p:home'); await self.cb(3,'p:list:0')
        self.assertFalse(any(m=='deleteMessage' and a['message_id'] in (701,702) for m,a in self.api.calls))
        await self.cb(3,'p:cancel:'+one['id'])
        self.assertTrue(any(m=='deleteMessage' and a['message_id']==701 for m,a in self.api.calls))
        self.assertFalse(any(m=='deleteMessage' and a['message_id']==702 for m,a in self.api.calls))

    async def test_success_notice_clickable_name_and_group_button_durable(self):
        order=self.p.new_order(99,3,self.pkg,buyer_name='Budi <3',target_kind='group')
        self.p.attach(order['id'],'tx1','000201',1000); self.p.qr_message(99,order['id'],3,703)
        self.p.accept(2,'tx1',1000)
        await self.ui.service.fulfill(order['id'])
        notices=[a for m,a in self.api.calls if m=='sendMessage' and a['chat_id']==2 and 'Pembayaran diterima' in a['text']]
        self.assertEqual(len(notices),1)
        self.assertIn('tg://user?id=3',notices[0]['text']); self.assertIn('Budi &lt;3',notices[0]['text'])
        self.assertIn('Harga: Rp1.000',notices[0]['text']); self.assertNotIn('Pesanan:',notices[0]['text'])
        success=next(a for m,a in self.api.calls if m=='sendMessage' and a['chat_id']==3 and 'Pembayaran berhasil!' in a['text'])
        self.assertEqual(success['reply_markup']['inline_keyboard'][0][0]['text'],'🔓 Masuk Grup')
        self.assertTrue(any(m=='deleteMessage' and a['message_id']==703 for m,a in self.api.calls))
        self.assertEqual(self.db.rows('SELECT * FROM display_screens WHERE bot=99 AND chat=3'),[])

    async def test_qr_delete_failure_clears_buttons_and_marks_status(self):
        o=self.p.new_order(99,3,self.pkg); self.p.attach(o['id'],'qrfail','000201',1000)
        self.p.qr_message(99,o['id'],3,704); self.p.cancel(99,3,o['id'])
        original=self.api.call
        async def fail_delete(method,**kw):
            if method=='deleteMessage': raise TelegramFailure(400,'cannot delete')
            return await original(method,**kw)
        self.api.call=fail_delete
        await self.ui.service.cleanup_qr(o['id'])
        self.assertTrue(any(m=='editMessageReplyMarkup' and a['message_id']==704 for m,a in self.api.calls))
        self.assertTrue(any(m=='editMessageCaption' and 'dibatalkan' in a['caption'] for m,a in self.api.calls))
        self.assertEqual(self.db.rows('SELECT cleared FROM payment_qr_messages')[0]['cleared'],1)

    async def test_history_keeps_snapshot_and_used_has_no_enter_button(self):
        o=self.p.new_order(99,3,self.pkg); self.p.attach(o['id'],'history1','000201',1000); self.p.accept(2,'history1',1000)
        self.p.save_package(99,2,self.pkg,name='New',price=2000)
        self.p.update(99,o['id'],used=1)
        await self.cb(3,'p:access:'+o['id'])
        text=self.latest()['text']; self.assertIn('VIP',text); self.assertIn('Rp1.000',text); self.assertIn('Akses sudah digunakan',text)
        self.assertNotIn('Masuk Channel',str(self.latest()['reply_markup']))
