import hashlib
import hmac
import unittest
from subgate.saweria import verify_signature, qr_amount, observation, recipient_from_html

class SaweriaTests(unittest.TestCase):
    def test_unknown_is_never_paid(self):
        for data in ({}, {'qr_string': ''}, {'status': 'PAID'}, {'qr_string': None}):
            self.assertNotEqual(observation(data), 'verified')

    def test_signature_and_tampering(self):
        body = dict(version='2022.01',id='tx',amount_raw=1000,donator_name='A',donator_email='a@b.c')
        signature = hmac.new(b'key', b'2022.01tx1000Aa@b.c', hashlib.sha256).hexdigest()
        self.assertTrue(verify_signature(body,signature,'key'))
        body['amount_raw']=999
        self.assertFalse(verify_signature(body,signature,'key'))
        self.assertFalse(verify_signature({},signature,'key'))

    def test_qr_currency_amount_and_crc(self):
        import binascii
        data='0002015303360540410006304'
        qr=data+format(binascii.crc_hqx(data.encode(),0xffff),'04X')
        self.assertEqual(qr_amount(qr),1000)
        with self.assertRaises(ValueError): qr_amount(qr[:-1]+'Z')
        with self.assertRaises(ValueError): qr_amount('000201')

    def test_recipient_changed_html_fails_closed(self):
        with self.assertRaises(ValueError): recipient_from_html('<html>changed</html>')


class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_reads_fragmented_body_fully(self):
        from subgate.saweria import Saweria
        class Content:
            async def iter_chunked(self,size):
                yield b'{"data":'
                yield b'{"id":"value"}}'
        class Response:
            status=200; content=Content()
            async def __aenter__(self): return self
            async def __aexit__(self,*args): pass
        class Session:
            def request(self,*args,**kwargs): return Response()
        self.assertEqual(await Saweria(Session()).request('https://test.invalid'),'{"data":{"id":"value"}}')
