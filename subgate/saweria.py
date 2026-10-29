"""Experimental Saweria transport. Explicit snap receipts can authorize access after identity and amount checks."""
import binascii
import hashlib
import hmac
import json
import re
import uuid
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
import aiohttp


class NextData(HTMLParser):
    def __init__(self):
        super().__init__()
        self.active, self.parts = False, []
    def handle_starttag(self,tag,attrs):
        if tag=='script' and dict(attrs).get('id')=='__NEXT_DATA__': self.active=True
    def handle_endtag(self,tag):
        if tag=='script': self.active=False
    def handle_data(self,text):
        if self.active: self.parts.append(text)


def recipient_from_html(html):
    parser=NextData(); parser.feed(html)
    try:
        return str(uuid.UUID(json.loads(''.join(parser.parts))['props']['pageProps']['data']['id']))
    except (ValueError,KeyError,TypeError):
        raise ValueError('Identitas akun Saweria belum dapat diverifikasi; struktur situs mungkin berubah.') from None


def verify_signature(body,signature,key):
    fields=('version','id','amount_raw','donator_name','donator_email')
    if not isinstance(body,dict) or not isinstance(signature,str) or not isinstance(key,str) or not key: return False
    if any(k not in body or not isinstance(body[k],(str,int)) or isinstance(body[k],bool) for k in fields): return False
    if type(body['amount_raw']) is not int or body['amount_raw']<=0: return False
    message=''.join(str(body[k]) for k in fields).encode()
    expected=hmac.new(key.encode(),message,hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected,signature)


def qr_amount(qr):
    if not isinstance(qr,str) or not qr.startswith('000201') or len(qr)>10000 or not re.fullmatch('[0-9a-fA-F]{4}',qr[-4:]):
        raise ValueError('Payload QRIS tidak dikenali.')
    if binascii.crc_hqx(qr[:-4].encode(),0xffff)!=int(qr[-4:],16): raise ValueError('Checksum QRIS tidak cocok.')
    fields={}; pos=0
    try:
        while pos<len(qr):
            tag=qr[pos:pos+2]; size=int(qr[pos+2:pos+4]); pos+=4
            if tag in fields or pos+size>len(qr): raise ValueError
            fields[tag]=qr[pos:pos+size]; pos+=size
        if fields.get('53')!='360' or fields.get('63')!=qr[-4:] or qr[-8:-4]!='6304': raise ValueError
        amount=Decimal(fields['54'])
        if not amount.is_finite() or amount!=amount.to_integral_value() or amount<=0: raise ValueError
        return int(amount)
    except (ValueError,KeyError,InvalidOperation):
        raise ValueError('Nominal/mata uang QRIS tidak dapat dipastikan.') from None


def observation(data):
    status=str(data.get('transaction_status',data.get('status',''))).strip().upper()
    if status in ('EXPIRED','FAILED','CANCELLED','CANCELED'): return status.lower()
    return 'unknown' if not data.get('qr_string') else 'pending'


def confirmed_receipt(data, transaction, username, amount):
    # Only explicit terminal states observed/identified for the QRIS snap route.
    # Empty QR, missing fields, errors and unknown statuses never settle orders.
    return (isinstance(data,dict) and data.get('id')==transaction
            and type(data.get('amount_raw')) is int and data['amount_raw']==amount
            and isinstance(data.get('username'),str) and data['username'].lower()==username.lower()
            and str(data.get('transaction_status','')).strip().upper() in ('SUCCESS','SETTLEMENT')
            and data.get('currency','IDR')=='IDR')


class Saweria:
    def __init__(self,session): self.session=session

    async def request(self,url,payload=None):
        try:
            async with self.session.request('GET' if payload is None else 'POST',url,json=payload,
                    timeout=aiohttp.ClientTimeout(total=25),headers={'User-Agent':'Zeisss-SubGate-Integration-Test/0.2'}) as response:
                if not 200<=response.status<300:
                    raise ValueError(f'Saweria HTTP {response.status}; belum ada konfirmasi pembayaran.')
                chunks=[]; size=0
                async for chunk in response.content.iter_chunked(65536):
                    size+=len(chunk)
                    if size>2_000_000: raise ValueError('Respons Saweria terlalu besar.')
                    chunks.append(chunk)
                raw=b''.join(chunks)
                return raw.decode()
        except (aiohttp.ClientError,TimeoutError,UnicodeError):
            raise ValueError('Koneksi Saweria bermasalah. Jangan membuat pembayaran berulang.') from None

    async def recipient(self,username):
        if not re.fullmatch(r'[a-z0-9]{1,80}',username): raise ValueError('Username Saweria hanya huruf kecil/angka.')
        return recipient_from_html(await self.request('https://saweria.co/'+username))

    async def create(self,account,amount,name,email,order):
        payload=dict(agree=True,notUnderage=True,message='Uji akses '+order,amount=amount,payment_type='qris',vote='',currency='IDR',
                     customer_info=dict(first_name=name,phone=''))
        if email: payload['customer_info']['email']=email
        raw=await self.request('https://backend.saweria.co/donations/'+account['recipient'],payload)
        try:
            data=json.loads(raw)['data']
            transaction=str(uuid.UUID(data['id']))
            total=qr_amount(data['qr_string'])
            if total<amount: raise ValueError
            if 'user_id' in data and data['user_id']!=account['recipient']: raise ValueError
            return dict(transaction_id=transaction,qr=data['qr_string'],total=total)
        except (ValueError,TypeError,KeyError):
            raise ValueError('Respons pembuatan QRIS tidak dapat dipastikan. Periksa Saweria sebelum mencoba lagi.') from None

    async def check(self,transaction):
        transaction=str(uuid.UUID(transaction))
        raw=await self.request('https://backend.saweria.co/donations/qris/snap/'+transaction)
        try:
            data=json.loads(raw)['data']
            if not isinstance(data,dict) or data.get('id')!=transaction: raise ValueError
            return data
        except (ValueError,TypeError,KeyError):
            raise ValueError('Status Saweria belum dapat dipastikan.') from None
