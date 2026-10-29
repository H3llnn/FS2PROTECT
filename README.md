# Zeisss SubGate

> Payment versi sederhana: hubungkan username Saweria, lalu bot memeriksa status transaksi otomatis tanpa stream key, webhook atau tunnel. Baca [panduan singkat](docs/PAYMENT-SIMPLE.md). Integrasi masih diuji; biaya bersih dan masa berlaku QRIS belum divalidasi sepenuhnya.


**Maintained by Zeisss.** Bot induk Telegram untuk menjalankan banyak bot berbagi
file dengan ForceSubs. Nama bot mengikuti nama masing-masing di Telegram.

## Fitur

- Bot induk: menu izin pengguna berdasarkan ID, `/buatbot`, daftar bot, hentikan/
  aktifkan bot. Jumlah bot tidak dibatasi aplikasi; sesuaikan kapasitas VPS.
- Setiap deploy meminta API ID, API hash, lalu token. Pembuat menjadi pemilik;
  pengguna lain tidak dapat mengambil alih bot yang sudah terdaftar.
- Cabut izin menghentikan semua bot pengguna. Setelah izin diberikan kembali,
  wajib deploy ulang. Bot ID yang sama memulihkan pengaturan dan link, termasuk
  setelah rotasi token. Tidak ada `/restart`.
- `/setting` khusus pemilik: satu channel database, maksimal empat ForceSubs,
  admin pembuat link, teks/foto sambutan, pesan wajib join, proteksi konten,
  hapus otomatis, dan teks pemberitahuannya.
- Semua ForceSubs wajib diikuti. Hanya target yang belum diikuti ditampilkan:
  `Join Channel` / `Join Group` tanpa nomor, lalu `Coba Lagi`.
- Pemilik/admin bebas ForceSubs. Admin tambahan hanya boleh membuat link.
- Kirim/teruskan file -> salin ke database -> link permanen. `/batch` -> file
  sesuai urutan -> `Selesai`. Caption asli tetap. Link menyimpan channel sumber,
  sehingga pergantian database tidak mengubah link yang sudah dibuat.
- Hapus otomatis default 30 menit, bisa diubah/dinonaktifkan. Pesan pemberitahuan
  terpisah mendukung `{durasi}` dan ikut dihapus. Jadwal bertahan saat restart.
- Broadcast khusus pemilik. Notifikasi gangguan satu kali per masalah ke pemilik,
  lalu satu notifikasi pemulihan. Kegagalan pemeriksaan tidak membebaskan akses.

## Pembaruan pesan, tombol, teks dan album

- Teks biasa dari pemilik/admin kini dapat menjadi link, termasuk dalam batch.
- Foto/video berurutan pada batch baru dikirim sebagai album, maksimal 10 media
  per album. Teks/dokumen tetap terpisah dan sesuai urutan. Album yang lebih besar
  dipecah otomatis. Link lama tanpa metadata media tetap dikirim satu per satu.
- Link memiliki tombol **📋 Salin Link**. Perlu aplikasi Telegram yang mendukung
  copy-text buttons; link tetap terlihat agar bisa disalin manual.
- Bot induk dan bot anak memakai pesan baru, tombol Kembali/Batal, preview,
  durasi pilihan cepat, detail bot/pengguna dan konfirmasi tindakan.
- Nama bot Telegram ditampilkan pada tombol daftar; username/ID hanya di detail.
- Formulir berakhir setelah 10 menit tidak aktif. Pengaturan khusus, kredensial,
  link dan jadwal penghapusan sebelumnya tetap disimpan. Pesan bawaan lama yang
  belum dikustomisasi diperbarui satu kali.
- Caption asli dipertahankan saat upload. Album baru memakai metadata file ID dan
  caption yang disimpan saat upload; mengedit/menghapus posting sumber kemudian
  tidak memperbarui metadata album yang sudah tersimpan. Akses admin ke channel
  sumber tetap diperiksa. Ini bukan fitur pencabutan link.
- Untuk memperbarui instalasi ZIP lokal: hentikan dengan Ctrl+C, cadangkan
  config.env dan folder data, salin folder subgate dari versi terbaru ke folder
  proyek lama, lalu jalankan main.py lagi. Jangan mengganti SECRET_KEY atau
  menghapus data. Tidak ada dependensi baru untuk pembaruan ini.

## Bot anak Payment

- Satu bot induk memberi izin ForceSubs, Payment, atau keduanya. Setiap bot anak memakai nama Telegram milik pemiliknya.
- Pemilik menghubungkan username Saweria melalui /setting. Pembeli memilih akses dan langsung menerima QRIS tanpa mengisi email. Pemeriksaan otomatis dan tombol Cek Pembayaran memakai validasi transaksi yang sama.
- Pembayaran terverifikasi menghasilkan undangan untuk satu anggota. Setelah dipakai, undangan dicabut. Pembelian bersifat permanen; keluar dari channel/grup tidak memberi hak masuk kembali lewat undangan lama.
- Pemilik mengatur nama, deskripsi, foto, harga, tujuan, urutan dan status akses. Admin Payment hanya mengedit tampilan akses/sambutan dan mengirim broadcast, setelah menekan /start dan berhasil menerima pemberitahuan izin.
- Pembelian Saya menyimpan pembelian berhasil. Tombol Coba Kirim Link Lagi memakai pesanan dan undangan yang sama jika pengiriman gagal; tidak meminta pembayaran ulang.
- Notifikasi pembayaran hanya ke pemilik, dengan nama pembeli yang bisa diklik, akses dan harga. Pesan bawaan untuk pembeli tidak menyebut penyedia pembayaran; pengaturan pemilik tetap menyebut Saweria.
- Menu/formulir baru menggantikan layar bot sebelumnya. QRIS aktif dipertahankan hingga dibatalkan atau pembayaran terverifikasi. Link akses, notifikasi dan hasil broadcast tetap tersimpan. Pesan pengguna tidak dihapus.
- Broadcast Payment memakai preview dan konfirmasi. Hanya pembuat dapat menghentikan dan menerima hasilnya. Tidak dilanjutkan otomatis setelah restart.
- Harga akses minimal Rp1.000. Integrasi memakai endpoint penyedia yang dapat berubah; status yang tidak jelas tidak membuka akses.

Panduan: [Payment sederhana](docs/PAYMENT-SIMPLE.md), [pembaruan terakhir](docs/PERAPIHAN-CARA-UPDATE.md).
Instalasi dari versi ForceSubs memerlukan pemasangan ulang requirements.txt karena Payment menambahkan qrcode/Pillow. Cadangkan config.env dan data; pertahankan SECRET_KEY.

## Persiapan

1. Python **3.12+**, satu VPS/server yang menyala terus, dan disk persisten.
2. Buat **bot induk** melalui [@BotFather](https://t.me/BotFather).
3. Siapkan ID Telegram kamu sebagai `MASTER_OWNER_ID`.
4. Setiap pembuat bot menyiapkan API ID/hash dari
   [my.telegram.org](https://my.telegram.org) dan token bot anak dari BotFather.

## Jalankan di VPS

```sh
git clone https://github.com/H3llnn/Zeisss-SubGate.git
cd Zeisss-SubGate
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp sample_config.env config.env
python -m subgate.keygen
# Salin kunci hasil perintah di atas ke SECRET_KEY dalam config.env.
# Isi MASTER_BOT_TOKEN dan MASTER_OWNER_ID. Jangan upload config.env.
chmod 600 config.env
python main.py
```

`DATA_DIR` menyimpan database SQLite. **Cadangkan direktori data beserta
SECRET_KEY secara privat.** Kehilangan kunci membuat kredensial tersimpan tidak
dapat dibaca. Simpan konfigurasi, database, dan sesi di luar Git. Jalankan hanya
**satu instance** untuk satu database; jangan gunakan token yang sama di layanan
lain atau webhook lain.

Alternatif Docker:

```sh
docker compose up -d --build
docker compose logs --tail=50
```

Compose memakai volume persisten dan hidup kembali setelah restart host.
Konfigurasi dibaca dari `config.env`. Jangan gunakan disk sementara untuk SQLite.
Jika menjalankan langsung tanpa Docker, gunakan pengelola proses VPS untuk
menjalankan kembali `python main.py` saat host menyala.

## Penggunaan

### Bot induk

- Kamu: `/start` -> **Tambah Izin** / **Cabut Izin** -> ID Telegram pengguna.
- Pembuat: `/buatbot` -> API ID -> API hash -> token. Ketiganya diminta lagi
  setiap deploy, termasuk deploy ulang. `/cancel` membatalkan input; formulir
  kedaluwarsa setelah 10 menit. Pesan kredensial tidak dihapus otomatis sesuai
  pilihan proyek. Gunakan chat privat dan lindungi akun Telegram tersebut.
- **Bot Saya** menampilkan bot milik pembuat. **Semua Bot** dan tombol status
  hanya untuk pemilik induk. Setelah dicabut, bot tidak dapat diaktifkan lewat
  tombol; pembuat harus deploy ulang sesudah diberi izin kembali.

### Bot anak

1. Pemilik membuka bot, menekan **Start**, lalu `/setting`.
2. Tambahkan bot sebagai admin di channel database dengan izin mengirim dan
   menghapus pesan. Masukkan ID melalui **Channel Database**.
3. Untuk ForceSubs, bot harus admin di setiap channel/supergroup dengan izin
   mengundang pengguna. Masukkan ID melalui **ForceSubs**. Group biasa perlu
   diubah menjadi supergroup agar pemeriksaan anggota dapat dilakukan.
4. Tambah ID admin pembuat link bila dibutuhkan. Kirim file atau `/batch`.
5. Pengguna membuka link, menekan Start jika Telegram memintanya, join seluruh
   target, lalu **Coba Lagi**. Kembali ke chat saja tidak otomatis menjalankan bot.
6. Pemilik memakai `/broadcast` lalu mengirim pesan, atau membalas pesan dengan
   `/broadcast`, lalu mengonfirmasi tombol. Broadcast tidak memakai jadwal
   penghapusan file, sehingga pengumuman tetap tersedia.

Teks pengaturan berupa teks biasa, maksimal 1000 karakter. Caption file tidak
diganti. Foto sambutan diunggah langsung sebagai foto, bukan dokumen.
Durasi penghapusan 0 (nonaktif) sampai 2879 menit: Telegram membatasi penghapusan
pesan hingga sekitar 48 jam. Jika server mati melewati batas itu, Telegram dapat
menolak penghapusan. Hapus otomatis tidak menjamin bebas ban.

## Data dan kompatibilitas

- Kredensial API/token/sesi dienkripsi dengan Fernet di SQLite. API ID/hash
  divalidasi melalui Telethon saat deploy. Operasi bot menggunakan Telegram Bot
  API agar channel privat dapat dikonfigurasi langsung menggunakan ID.
- Bot aktif kembali setelah server restart. Penghapusan yang terlewat diproses.
  Bot berhenti juga tetap membersihkan pesan yang sudah dijadwalkan tanpa
  melayani permintaan baru.
- Link tidak memiliki masa kedaluwarsa. Bot tetap perlu menjadi admin di channel
  sumber dan pesan sumber harus tersedia. Proteksi konten pada channel sumber
  dapat menghalangi penyalinan file oleh Telegram.
- Data terpisah per **ID bot**, bukan username/token. Ini mengganti arsitektur
  repo lama: database PostgreSQL/Pyrogram dan link lama FS2PROTECT **tidak otomatis
  diimpor**. Cabang `backup/fs2protect-before-subgate` menyimpan versi sebelumnya.
- Draft batch/formulir dan broadcast berjalan tidak dilanjutkan setelah restart;
  mulai ulang proses itu. File sumber yang sudah tersimpan tetap ada.
- Jika proses mati tepat setelah Telegram menerima pengiriman tetapi sebelum ID
  pesan tersimpan ke SQLite, pesan itu mungkin memerlukan penghapusan manual.

## Pengujian

```sh
python -m unittest discover -s tests -v
python -m compileall -q subgate tests main.py
```

Pengujian memakai Telegram palsu dan SQLite nyata untuk otorisasi, isolasi bot,
revokasi/deploy ulang, ForceSubs, urutan file, template, dan jadwal penghapusan.
Uji langsung dengan token dan channel percobaan tetap diperlukan sebelum dipakai
publik. Jangan masukkan token produksi ke pengujian atau CI.

## Lisensi dan kredit

GPL-3.0, lihat [LICENSE](LICENSE). Kredit proyek/kode asal: CodexBotz /
[File-Sharing-Bot](https://github.com/CodeXBotz/File-Sharing-Bot), mrismanaziz,
Paijoo, Dyecstar, dan kontributor FS2PROTECT sebelumnya. SubGate dikelola Zeisss.
Kredit tersebut tidak memberi akses admin kepada siapa pun.
