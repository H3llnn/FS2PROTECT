import unittest
from pathlib import Path
from cryptography.fernet import Fernet
import tempfile
from subgate.store import Store
from subgate.payment_store import PaymentStore
from subgate.payment_service import PaymentService
from test_payment_service import FakePayAPI

class PolishRestartTests(unittest.IsolatedAsyncioTestCase):
    async def test_pending_qr_cleanup_and_snapshot_survive_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'db'; key=Fernet.generate_key()
            db=Store(path,key,1); db.grant(1,2,'both'); db.deploy(2,99,'Pay',1,'h','t','s',kind='payment')
            p=PaymentStore(db); p.account(2,'example','recipient',enabled=True)
            ident=p.save_package(99,2,name='VIP',price=1000,target=-1001)
            order=p.new_order(99,3,ident,buyer_name='Budi',target_kind='channel')
            p.attach(order['id'],'tx','000201',1000); p.qr_message(99,order['id'],3,900)
            p.mark_started(99,4); p.move(99,2,ident,1)
            p.cancel(99,3,order['id'])
            db.close()
            db=Store(path,key,1); p=PaymentStore(db); api=FakePayAPI()
            await PaymentService(db,99,api,None).tick(active=False)
            self.assertTrue(any(m=='deleteMessage' and a['message_id']==900 for m,a in api.calls))
            self.assertTrue(p.started(99,4)); self.assertEqual(p.order(99,order['id'])['buyer_name'],'Budi')
            self.assertEqual(p.package(99,ident)['name'],'VIP')
            db.close()
