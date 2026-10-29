> DOKUMEN HISTORIS VERSI WEBHOOK. Untuk versi terbaru, gunakan PAYMENT-SIMPLE.md. Webhook kini opsional dan hanya aktif dengan PAYMENT_ENABLE_WEBHOOK=1.

# Zeisss SubGate Payment — versi uji 25 Oktober 2026

## Yang sudah diimplementasikan
- Satu induk, anak ForceSubs atau Payment, nama mengikuti BotFather.
- Izin ForceSubs/Payment/keduanya, pencabutan per jenis, data lama tetap ForceSubs.
- Paket satu channel/supergroup privat, nama/deskripsi/harga/foto, edit/nonaktif/hapus.
- Katalog hanya nama; detail foto opsional; beberapa order aktif dan pembelian berulang.
- QRIS Saweria dibuat per pesanan, dikirim sebagai PNG langsung dalam chat.
- Cek otomatis dan tombol Cek Pembayaran melalui satu layanan; tombol Batalkan.
- Verifikasi signature webhook, ID transaksi unik, pencocokan nominal, replay idempotent.
- Link baru untuk satu orang setelah pembayaran terverifikasi, dicabut setelah join terdeteksi.
- Riwayat pembelian berhasil, akses belum terpakai bisa diambil, status Sudah digunakan.
- Notifikasi pemilik, transaksi bot khusus pemilik, retry pengiriman dan pencabutan.
- Snapshot harga/target, pembatalan order belum dibayar ketika paket dinonaktifkan/dihapus atau bot dihentikan.
- Pesanan dibayar setelah dibatalkan dicatat tanpa akses otomatis.
- Kunci streaming, payload QRIS dan link undangan tersimpan terenkripsi memakai SECRET_KEY lama.

## Batas versi ini — baca sebelum membayar
Ini belum rilis produksi. Pembuatan QRIS Rp1.000 sudah dicoba pengguna pada skrip terpisah dan tercatat di dashboard, tetapi alur webhook + bot + undangan nyata belum diuji end-to-end.
Endpoint QRIS Saweria belum ditemukan dokumentasi resmi publiknya. Polling yang mengembalikan QR kosong atau PAID tanpa bukti autentik tidak membuka akses. Dalam versi ini bukti lunas berasal dari HTTP Webhook Saweria bertanda tangan.
Karena itu setup memerlukan username DAN kunci streaming akun milik pemilik, serta URL webhook HTTPS publik. Ini tambahan terhadap contoh layanan username saja. Jika webhook belum siap, pembelian diblokir, bukan diganti verifikasi manual.
Harga paket adalah nominal yang diminta ke Saweria. Selisih nominal QRIS ditampilkan sebagai tambahan pada QRIS. Potongan layanan terhadap penerima belum otomatis di-gross-up; belum memenuhi janji pemilik menerima harga paket bersih. Minimum, biaya dan expiry masih perlu dibuktikan.
Tidak ada timer kedaluwarsa order dari bot. Ini tidak memperpanjang masa berlaku QRIS penyedia. Status expired/failed ditampilkan sebagai pengamatan; order tidak otomatis diperbarui atau ditandai lunas.
Jangan berjualan akses digital memakai QRIS di bot sebelum menyelesaikan konflik aturan Telegram Stars: https://core.telegram.org/bots/payments-stars . Pengujian teknis tidak membuktikan penggunaan ini diperbolehkan penyedia/platform.

## Persiapan lokal
1. Ekstrak ZIP ke FOLDER BARU. Hentikan proses lama hanya jika akan memakai token yang sama; satu token tidak boleh dipolling dua proses.
2. Gunakan Python 3.12+ dan buat virtual environment seperti README. Install semua requirements.txt; ada dependensi baru qrcode dengan Pillow.
3. Untuk uji awal pakai bot induk, bot anak dan channel/supergroup percobaan. Jangan mulai dengan database produksi.
4. Salin sample_config.env menjadi config.env, isi token induk, ID pemilik, SECRET_KEY, DATA_DIR baru. Jangan kirim isinya ke chat atau GitHub.
5. Jalankan python main.py. Tanpa PAYMENT_PUBLIC_BASE, ForceSubs dan menu Payment dapat dicoba, tetapi checkout Payment belum dibuka.

## Menyiapkan webhook
Tambahan konfigurasi:
PAYMENT_PUBLIC_BASE=https://alamat-https-milikmu
PAYMENT_BIND=127.0.0.1
PAYMENT_PORT=8080

Sediakan reverse proxy atau tunnel HTTPS yang meneruskan POST /saweria/... ke listener lokal tersebut. Jangan menganggap localhost dapat dihubungi Saweria. URL publik dan listener yang sedang aktif harus sesuai. Biarkan bind loopback untuk proses lokal; pengaturan Docker memerlukan penerusan port/jaringan tersendiri dan tidak otomatis disediakan oleh compose lama.
Jangan pakai URL HTTP publik. Jangan taruh token Telegram, kunci streaming atau password di URL. Listener mematikan access log URL privatnya.
Jika server memiliki PAYMENT_PUBLIC_BASE, listener harus berhasil start terlebih dahulu sebelum checkout diaktifkan. Port yang sudah digunakan membuat startup gagal dengan jelas, bukan fallback tanpa verifikasi.

## Alur pengaturan bot
1. Di induk: Tambah Izin -> ID pengguna -> ForceSubs/Payment/Keduanya. Izin lama tetap ForceSubs saja. Ubah Jenis Izin mengganti pilihan dan menghentikan jenis yang tidak diizinkan.
2. Buat Bot -> pilih Payment (jika punya dua izin) -> API ID -> API hash -> token bot anak.
3. Buka anak -> /setting -> Hubungkan Saweria -> username milikmu -> kunci streaming dari akun yang sama. Kunci disimpan terenkripsi dan pesan kunci dicoba dihapus tanpa menggemakannya.
4. Baca keterbatasan dan aktifkan mode uji. URL webhook privat akan ditampilkan. Tempel di HTTP Webhook akun Saweria dan aktifkan. Satu akun milik pengguna dapat dipakai beberapa botnya dengan URL yang sama.
5. /setting -> Kelola Paket -> Tambah Paket -> nama/deskripsi/harga/ID privat. Tambahkan bot sebagai admin dengan izin mengundang. Foto opsional diubah dari detail paket.
6. Pilih Paket -> detail -> Beli -> email nyata -> persetujuan ketentuan/usia -> gambar QRIS. Periksa penerima dan total melalui bank/e-wallet sebelum membayar.
7. Tunggu webhook. Maintenance memproses akses berikutnya; Cek Pembayaran menjadi cadangan, tetapi tidak dapat menggantikan bukti lunas yang belum diterima.
8. Cocokkan di dashboard Saweria, riwayat pembeli, Transaksi Bot pemilik, link satu orang dan pencabutannya setelah join.

## Pemulihan dan batas undangan
Pengiriman gagal dicoba kembali dengan link tersimpan yang sama. Pekerjaan dijadwalkan ulang agar order lama bermasalah tidak menahan order baru.
Jika proses mati ketika createChatInviteLink sedang berjalan, hasil Telegram dapat ambigu. Sistem tidak membuat link kedua otomatis. Pemilik diberi tahu untuk memeriksa undangan bernama SG-IDPESANAN di pengaturan target; pemulihan kasus ini masih manual oleh operator, belum ada tombol rekonsiliasi.
Pencabutan setelah join bergantung pada update chat_member. Gangguan server, update yang terlewat atau hilangnya akses admin dapat menunda/menghalangi pencabutan. member_limit=1 sendiri bukan jaminan satu pemakaian selamanya. Jangan menjanjikan anti-pakai-ulang tanpa uji kejadian tersebut.
Pembatalan lokal tidak membatalkan QRIS penyedia. Jangan membayar QRIS order yang sudah dibatalkan. Pembayaran terlambat tetap dicatat dan diberitahukan, tanpa refund atau akses otomatis.
Mengganti akun penerima ditolak ketika masih ada pembayaran pending, termasuk order dibatalkan yang mungkin masih dapat dibayar. Rotasi kunci akun yang sama bisa diperlukan tetapi webhook lama dapat gagal; periksa dashboard dan jangan menganggap otomatis terselesaikan.

## Memperbarui instalasi lama setelah uji
Hentikan bot. Cadangkan config.env, seluruh DATA_DIR dan SECRET_KEY secara privat. Salin folder subgate baru dan requirements.txt; install requirements pada venv yang dipakai. Pertahankan konfigurasi, kunci dan data lama. Start kembali.
Migrasi menambah tabel/kolom; link, jadwal dan setting ForceSubs lama dipertahankan. Rollback paling aman dengan source lama DAN cadangan database dari sebelum migrasi, ketika proses berhenti. Jangan menghapus data untuk mengatasi error.
ZIP tidak berisi config.env, data pengguna, token atau virtual environment. Tidak ada push/deploy GitHub pada pekerjaan ini.

## Pengujian pengembang
python -m unittest discover -s tests -v
python -m compileall -q subgate tests main.py
Tes memakai SQLite nyata dan API Telegram/Saweria palsu; bukan transaksi uang nyata. Cakupan mencakup migrasi, isolasi, callback awal/replay/signature salah, pembatalan, pengiriman ganda, retry, antrean, QR PNG dan ForceSubs lama.

## Referensi kode dan lisensi
Mekanisme Saweria dipelajari dari nindtz/saweriaqris (MIT). Pemisahan client/job/catalog/SQLite dipelajari dari mocasus/telegram-auto-order-bot (MIT). Notice disertakan pada THIRD_PARTY_NOTICES.md. Implementasi ditulis untuk fondasi SubGate; tidak memasang aplikasi tersebut sebagai dependensi.
Kstriabintang/telegram-autoorder-bot dipakai untuk memahami pola umum order, bukan menyalin kode: LICENSE belum ditemukan pada pemeriksaan. Beridonasi memakai QR generator pihak ketiga dan verifikasi manual sehingga tidak diintegrasikan.
Lisensi repo utama tetap GPL-3.0; kredit wajib tetap dipertahankan.
