"""Orders, verification observations and durable invitation fulfillment."""
import asyncio
import time
from .payment_store import PaymentStore
from .copy import h, panel
from .service import TelegramFailure, inline
from .copy import button,link_button


class PaymentService:
    def __init__(self,db,bot,api,provider):
        self.db,self.bot,self.api,self.provider=db,bot,api,provider
        self.store=PaymentStore(db)
        self.lock=asyncio.Lock()

    async def target(self,chat):
        info=await self.api.call('getChat',chat_id=chat)
        member=await self.api.call('getChatMember',chat_id=chat,user_id=self.bot)
        if info.get('type') not in ('channel','supergroup') or info.get('username') or info.get('active_usernames'):
            raise ValueError('Target harus channel/grup privat tanpa username publik.')
        if member.get('status')!='creator' and not (member.get('status')=='administrator' and member.get('can_invite_users')):
            raise ValueError('Bot harus admin dengan izin mengundang anggota.')
        return info

    async def notice(self,scope,text):
        # Mark only after send so transient failures remain retryable.
        if any(r['bot']==self.bot and r['scope']==scope for r in self.db.incidents()): return
        await self.api.call('sendMessage',chat_id=self.db.bot(self.bot)['owner'],text=text,parse_mode='HTML')
        self.db.incident(self.bot,scope,True)

    async def create(self,user,package,name,email):
        p=self.store.package(self.bot,package)
        info=await self.target(p['target'])
        order=self.store.new_order(self.bot,user,package,buyer_name=name,target_kind='channel' if info['type']=='channel' else 'group')
        account=self.store.account(order['owner'])
        try:
            result=await self.provider.create(account,order['price'],name,email,order['id'])
            self.store.attach(order['id'],result['transaction_id'],result['qr'],result['total'])
        except (ValueError,TelegramFailure):
            # A failed POST might have succeeded remotely. Never retry automatically.
            self.store.cancel(self.bot,user,order['id'])
            await self.notice('payment:create:'+order['id'],panel('Pembuatan QRIS perlu diperiksa 🔎',
                'Pesanan '+h(order['id'])+' belum dapat dipastikan. Periksa Saweria sebelum membuat transaksi ulang.'))
            raise
        return self.store.order(self.bot,order['id'])

    async def check(self,ident,user=None,force=False):
        order=self.store.order(self.bot,ident,user)
        if order['payment']!='pending':
            await self.fulfill(ident)
            return order['payment']
        if not order['transaction_id']: return 'unknown'
        now=time.time()
        if now-order['checked']<15: return 'pending'
        self.store.update(self.bot,ident,checked=now)
        status=await self.provider.check(order['transaction_id'])
        if isinstance(status,dict):
            from .saweria import confirmed_receipt,observation
            account=self.store.account(order['owner'])
            if account and account['recipient']==order['recipient'] and confirmed_receipt(
                    status,order['transaction_id'],account['username'],order['price']):
                self.store.accept(order['owner'],order['transaction_id'],order['price'])
                await self.fulfill(ident)
                return self.store.order(self.bot,ident)['payment']
            return observation(status)
        return 'unknown' 

    async def fulfill(self,ident):
        async with self.lock:
            order=self.store.order(self.bot,ident)
            if order['payment']=='late':
                if not order['notified']:
                    await self.api.call('sendMessage',chat_id=order['owner'],parse_mode='HTML',text=panel(
                        'Pembayaran setelah pembatalan 🔎',f'Pesanan: {h(ident)}\nAkses: {h(order["name"])}\nNominal: Rp{order["price"]:,}\nAkses tidak dikirim otomatis.'))
                    self.store.update(self.bot,ident,notified=1)
                return
            if order['payment']!='verified': return
            await self.cleanup_qr(ident)
            if not order['target_kind'] and not order['used']:
                try:
                    info=await self.api.call('getChat',chat_id=order['target'])
                    if info.get('type') in ('channel','supergroup','group'):
                        order['target_kind']='channel' if info['type']=='channel' else 'group'
                        self.store.update(self.bot,ident,target_kind=order['target_kind'])
                except TelegramFailure: pass
            if not order['notified']:
                try:
                    await self.api.call('sendMessage',chat_id=order['owner'],parse_mode='HTML',text=panel('🔔 Pembayaran diterima',await self.summary(order)),link_preview_options={'is_disabled':True})
                    self.store.update(self.bot,ident,notified=1)
                except TelegramFailure: pass
            if order['used']:
                if not order['revoked'] and order['invite']:
                    try:
                        await self.api.call('revokeChatInviteLink',chat_id=order['target'],invite_link=order['invite'])
                        self.store.update(self.bot,ident,revoked=1)
                    except TelegramFailure:
                        await self.notice('payment:revoke:'+ident,panel('Undangan perlu perhatian 🔧','Pencabutan link pesanan '+h(ident)+' belum berhasil dan akan dicoba lagi.'))
                return
            record=self.db.bot(self.bot)
            if not record['active'] or not self.db.allowed(order['owner'],'payment'): return
            if not order['invite']:
                if order['delivery'] in ('creating','uncertain'):
                    await self.notice('payment:uncertain:'+ident,panel('Periksa undangan pesanan 🔎',
                        'Pembuatan undangan '+h(ident)+' terputus. Periksa tautan bernama SG-'+h(ident)+' pada pengaturan channel; tidak membuat link kedua otomatis.'))
                    return
                try:
                    info=await self.target(order['target'])
                    if not order['target_kind']:
                        self.store.update(self.bot,ident,target_kind='channel' if info['type']=='channel' else 'group')
                        order['target_kind']='channel' if info['type']=='channel' else 'group'
                except (ValueError,TelegramFailure):
                    await self.access_failure(order,'target')
                    return
                self.store.update(self.bot,ident,delivery='creating',invite_name='SG-'+ident)
                try:
                    invite=await self.api.call('createChatInviteLink',chat_id=order['target'],name='SG-'+ident,member_limit=1)
                    url=invite['invite_link']
                    if not isinstance(url,str) or not url.startswith('https://t.me/+'): raise ValueError('Undangan tidak dikenali.')
                    self.store.update(self.bot,ident,invite=url,delivery='ready')
                except TelegramFailure as exc:
                    self.store.update(self.bot,ident,delivery='uncertain' if exc.code>=500 else 'ready')
                    await self.access_failure(order,'invite')
                    return
                order=self.store.order(self.bot,ident)
            record=self.db.bot(self.bot)
            if not record['active'] or not self.db.allowed(order['owner'],'payment'): return
            if not order['delivered']:
                try:
                    await self.api.call('sendMessage',chat_id=order['buyer'],parse_mode='HTML',text=panel('✨ Pembayaran berhasil!',
                        f'📦 Akses: <b>{h(order["name"])}</b>\n\nAksesmu sudah siap. Selamat menikmati 🤍'),
                        reply_markup=inline([[self.access_button(order)]]))
                    from .display import Display
                    await Display(self.db.conn,self.api).replace(self.bot,order['buyer'],[])
                    self.store.update(self.bot,ident,delivered=1,delivery='sent')
                except TelegramFailure:
                    await self.access_failure(order,'delivery')
                    return

    async def join(self,event):
        member=event.get('new_chat_member',{})
        joined=member.get('status') in ('member','administrator','creator') or (member.get('status')=='restricted' and member.get('is_member') is True)
        if not joined: return
        url=event.get('invite_link',{}).get('invite_link')
        if not url: return
        for row in self.db.rows("SELECT id FROM payment_orders WHERE bot=? AND target=? AND payment='verified' AND used=0 AND invite IS NOT NULL", (self.bot,event.get('chat',{}).get('id'))):
            order=self.store.order(self.bot,row['id'])
            if order['invite']==url:
                self.store.update(self.bot,row['id'],used=1)
                await self.fulfill(row['id'])
                return

    async def tick(self,active=True):
        await self.cleanup_qr()
        # Schedule before I/O so a failing old order never starves newer work.
        for row in self.store.work(self.bot):
            self.store.update(self.bot,row['id'],work_due=time.time()+60)
            try: await self.fulfill(row['id'])
            except (ValueError,TelegramFailure): pass
        if active and self.provider:
            slots=asyncio.Semaphore(3)
            async def check(row):
                async with slots:
                    try: await self.check(row['id'])
                    except (ValueError,TelegramFailure): pass
            await asyncio.gather(*(check(row) for row in self.store.pending(self.bot,time.time(),limit=10)))

    async def member_name(self,order):
        name=order.get('buyer_name') or ''
        if not name:
            try:
                chat=await self.api.call('getChat',chat_id=order['buyer'])
                name=' '.join(x for x in (chat.get('first_name'),chat.get('last_name')) if x)
            except TelegramFailure: pass
            name=name or 'Anggota'
            self.store.update(self.bot,order['id'],buyer_name=name)
        return name

    async def summary(self,order):
        name=await self.member_name(order)
        member=f'<a href="tg://user?id={order["buyer"]}">{h(name)}</a>'
        price=f'{order["price"]:,}'.replace(',','.')
        return f'👤 Anggota: {member}\n📦 Akses: {h(order["name"])}\n💰 Harga: Rp{price}'

    def access_button(self,order):
        label={'group':'🔓 Masuk Grup','channel':'🔓 Masuk Channel'}.get(order.get('target_kind'),'🔓 Buka Akses')
        return link_button(label,order['invite'])

    async def access_failure(self,order,scope):
        await self.notice('payment:'+scope+':'+order['id'],panel('⚠️ Akses belum terkirim',
            await self.summary(order)+'\n\nPembayaran sudah diterima. Bot akan mencoba mengirim akses kembali.'))

    async def cleanup_qr(self,ident=None):
        if ident is None:
            rows=self.store.qr_due(self.bot)
        else:
            order=self.store.order(self.bot,ident)
            if order['state']!='cancelled' and order['payment']!='verified': return
            rows=self.db.rows('SELECT * FROM payment_qr_messages WHERE bot=? AND order_id=? AND cleared=0',(self.bot,ident))
        for row in rows:
            order=self.store.order(self.bot,row['order_id'])
            done=False
            try:
                await self.api.call('deleteMessage',chat_id=row['chat'],message_id=row['message_id'])
                done=True
            except TelegramFailure:
                try:
                    await self.api.call('editMessageReplyMarkup',chat_id=row['chat'],message_id=row['message_id'],reply_markup=inline([]))
                    status='✅ Pembayaran berhasil' if order['payment']=='verified' else '🍃 Pesanan dibatalkan'
                    await self.api.call('editMessageCaption',chat_id=row['chat'],message_id=row['message_id'],caption=status)
                    done=True
                except TelegramFailure: pass
            with self.db.conn:
                self.db.conn.execute('UPDATE payment_qr_messages SET cleared=?,next_try=? WHERE bot=? AND chat=? AND message_id=?',
                    (done,time.time()+60,self.bot,row['chat'],row['message_id']))
