# Payment sederhana — 26 Oktober 2026

Pemilik cukup memasukkan username Saweria. Tidak perlu stream key, webhook, PAYMENT_PUBLIC_BASE atau Cloudflare Tunnel.

## Memasang pembaruan ke versi Payment Uji sebelumnya
1. Di terminal BOT, Ctrl+C. Buat cadangan privat config.env dan folder data.
2. Ekstrak ZIP pembaruan ke folder terpisah.
3. Salin folder subgate dari ZIP ke folder bot yang berisi main.py. Pilih ganti file ketika diminta. Pertahankan config.env, SECRET_KEY, folder data dan .venv yang sudah digunakan.
4. Jalankan: .\.venv\Scripts\python.exe main.py
5. Di bot anak: /setting -> Hubungkan Saweria -> kirim username milikmu. Selesai.

Terminal Cloudflare boleh ditutup. Nilai PAYMENT_PUBLIC_BASE lama diabaikan kecuali PAYMENT_ENABLE_WEBHOOK=1 sengaja disetel oleh operator.
Tidak ada dependensi baru dibanding versi Payment Uji sebelumnya.

## Hasil investigasi
Pada transaksi percobaan Rp1.000 yang sebelumnya dibayar pengguna, GET endpoint lama mengembalikan QR kosong tanpa status. GET /donations/qris/snap/{id} pada server Saweria mengembalikan transaction_status=SUCCESS, dengan ID, amount_raw dan username sesuai catatan lokal. Pengujian ini hanya membaca transaksi lama; tidak membuat QR atau pembayaran baru.
Kode sekarang memakai endpoint kedua. Pembayaran diproses hanya untuk SUCCESS/SETTLEMENT dengan ID, nominal bulat dan username cocok. QR kosong, data kurang, pending, gagal, expired, identitas/nominal tidak cocok atau error jaringan tidak membuka akses.
ID transaksi tetap unik. Pemeriksaan manual/otomatis memakai jalur yang sama; pembayaran setelah pembatalan tetap late dan tidak membuka akses. Webhook lama tetap opsional, bukan syarat setup. Signature dengan kunci kosong ditolak.

## Batas bukti
Status sukses satu transaksi nyata sudah dibaca. Pending/expired/gagal dan mismatch diuji dengan respons tiruan; belum semuanya diamati sebagai transaksi nyata. Alur lengkap bot Telegram sampai join/revoke masih perlu dicoba pada channel percobaan. Perhitungan seluruh potongan Saweria dan masa berlaku QRIS belum dinyatakan selesai.
Username hanya menentukan penerima, tidak membuktikan kepemilikan akun. Pastikan username milikmu dan periksa penerima/nominal di aplikasi pembayar. Endpoint Saweria yang dipakai belum terdokumentasi resmi publik dan dapat berubah; jika status tidak jelas, akses ditahan.
Aturan Telegram untuk penjualan digital dan persyaratan Saweria tetap berlaku. Pembaruan teknis ini tidak menyelesaikan batas aturan platform tersebut.

Referensi yang mengarahkan investigasi: https://github.com/hokireceh/Saweria-Payment-Module dan https://github.com/edihardi/digiroot/blob/main/lib/saweria.ts . Endpoint dan perilakunya diperiksa langsung untuk transaksi milik pengguna; kode repo tersebut tidak disalin dan tidak dilakukan bypass proteksi layanan.
