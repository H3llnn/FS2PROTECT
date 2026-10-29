# Pembaruan teks dan tombol Zeisss SubGate

1. Hentikan bot dengan Ctrl+C. Simpan cadangan config.env dan folder data.
2. Ekstrak ZIP ini, lalu salin folder subgate ke folder bot yang berisi main.py. Pilih Ganti file di tujuan.
3. Jangan ganti config.env, SECRET_KEY, data atau .venv.
4. Jalankan kembali dengan perintah yang biasa digunakan: .\.venv\Scripts\python.exe main.py
5. Buka ulang menu/detail akses di Telegram. Pesan lama yang sudah terkirim tidak diubah oleh pembaruan ini.

Perubahan:
- Semua teks yang disetujui pada diskusi terakhir diterapkan pada Payment.
- Tombol Transaksi di pengaturan owner dihapus. Catatan pembayaran di database tetap disimpan.
- Pesan bawaan dan error untuk pembeli tidak menyebut Saweria. Pengaturan/notifikasi teknis khusus owner tetap boleh menyebutnya. Teks kustom milik owner dan nama penerima pada aplikasi pembayaran tidak diubah.
- Pembelian Saya menampilkan Coba Kirim Link Lagi pada pesanan terverifikasi yang belum terkirim dan belum digunakan.
- Percobaan ulang memeriksa pemilik pesanan, memakai undangan yang sama dan tidak mengulang pengiriman yang sudah berhasil. Jika pembuatan undangan sebelumnya tidak dapat dipastikan, bot tetap membutuhkan pemeriksaan owner agar tidak membuat undangan kedua.
- Pembeli tidak diminta email. Pemeriksaan pembayaran otomatis dipertahankan.

Tidak ada dependensi baru dibanding versi Payment sebelumnya atau perubahan kredensial. Tes memakai Telegram dan penyedia pembayaran tiruan; setelah memasang, periksa tampilan pada bot percobaan sebelum dipakai luas.
