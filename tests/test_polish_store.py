import unittest
import test_payment_store as fixtures

class PolishStoreTests(unittest.TestCase):
    setUp=fixtures.PaymentStoreTests.setUp
    tearDown=fixtures.PaymentStoreTests.tearDown
    def test_staff_allowlist(self):
        self.db.admin(99,2,4,True)
        self.p.save_package(99,4,self.pkg,name='Changed')
        self.assertEqual(self.p.package(99,self.pkg)['name'],'Changed')
        for values in ({'price':2000},{'target':-1002}):
            with self.assertRaises(PermissionError): self.p.save_package(99,4,self.pkg,**values)
        with self.assertRaises(PermissionError): self.p.save_package(99,4,name='New',price=1000,target=-1002)
        with self.assertRaises(PermissionError): self.p.package_status(99,4,self.pkg,'inactive')
        with self.assertRaises(PermissionError): self.p.move(99,4,self.pkg,1)
        self.db.setting(99,4,'payment_welcome','Hello')
        with self.assertRaises(PermissionError): self.db.setting(99,4,'database',-1003)
    def test_price_minimum(self):
        with self.assertRaises(ValueError): self.p.save_package(99,2,self.pkg,price=500)
    def test_order_move_preserves_history(self):
        other=self.p.save_package(99,2,name='Other',price=2000,target=-1002)
        order=self.p.new_order(99,3,self.pkg,buyer_name='Budi',target_kind='group')
        self.p.move(99,2,other,-1)
        self.assertEqual([p['id'] for p in self.p.packages(99)],[other,self.pkg])
        self.p.save_package(99,2,self.pkg,name='New',price=3000)
        saved=self.p.order(99,order['id'])
        self.assertEqual((saved['name'],saved['price'],saved['buyer_name'],saved['target_kind']),('VIP',1000,'Budi','group'))
