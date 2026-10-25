"""Approved message helpers and Telegram keyboard buttons."""
from html import escape

def h(value):
    return escape(str(value), quote=False)

def panel(title, body=''):
    return f'<b>✦ {title}</b>' + ('\n\n'+body if body else '')

def pretty(text):
    first, sep, rest = text.partition('\n')
    return ('<b>'+h(first)+'</b>'+sep+h(rest)) if first.startswith('✦') else h(text)

def button(text, data):
    return {'text': text, 'callback_data': data}

def link_button(text, url):
    return {'text': text, 'url': url}

def copy_button(link):
    return {'text': '📋 Salin Link', 'copy_text': {'text': link}}

def minutes(seconds):
    if not seconds:
        return 'Nonaktif'
    return f'{seconds//60} menit' if seconds % 60 == 0 else f'{seconds} detik'

def nav(back):
    return [[button('‹ Kembali', back), button('✕ Batal', 'x:cancel')]]

DENIED_UPLOAD = panel('Akses terbatas 🔐', 'Pembuatan link hanya tersedia untuk pemilik dan admin bot ini.')
INVALID_LINK = panel('Kontennya belum ditemukan 🔎', 'Link ini tidak valid atau sudah tidak tersedia.\nPastikan kamu membuka link yang benar, ya.')
UNAVAILABLE = panel('Ada kendala sebentar 🔧', 'Kontenmu belum bisa dikirim.\nCoba lagi beberapa saat lagi, ya.')
