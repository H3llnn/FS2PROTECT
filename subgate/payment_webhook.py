"""Optional authenticated Saweria callbacks. No access based on polling guesses."""
import json
from aiohttp import web
from .payment_store import PaymentStore
from .saweria import verify_signature


class PaymentWebhook:
    def __init__(self,db,manager,public_base='',host='127.0.0.1',port=8080):
        self.db,self.manager=db,manager
        self.public_base=public_base.rstrip('/')
        self.host,self.port=host,port
        self.runner=None

    async def receive(self,request):
        rows=self.db.rows('SELECT owner FROM payment_accounts WHERE route=?',(request.match_info['route'],))
        if not rows: raise web.HTTPNotFound()
        store=PaymentStore(self.db)
        account=store.account(rows[0]['owner'])
        try: body=await request.json()
        except (ValueError,UnicodeError): raise web.HTTPBadRequest() from None
        signature=request.headers.get('Saweria-Callback-Signature','')
        if not verify_signature(body,signature,account['key']): raise web.HTTPForbidden()
        try: result=store.accept(account['owner'],body['id'],body['amount_raw'])
        except ValueError: raise web.HTTPConflict(text='Transaction mismatch') from None
        # Maintenance delivers asynchronously; HTTP acknowledgement is durable.
        return web.json_response({'received':True,'result':result})

    async def start(self):
        if not self.public_base: return
        if not self.public_base.startswith('https://') or '?' in self.public_base or '#' in self.public_base:
            raise ValueError('PAYMENT_PUBLIC_BASE harus URL HTTPS tanpa query/fragment.')
        app=web.Application(client_max_size=32*1024)
        app.router.add_post('/saweria/{route}',self.receive)
        self.runner=web.AppRunner(app,access_log=None)
        await self.runner.setup()
        await web.TCPSite(self.runner,self.host,self.port).start()
        self.manager.payment_base=self.public_base

    async def close(self):
        if self.runner: await self.runner.cleanup()
