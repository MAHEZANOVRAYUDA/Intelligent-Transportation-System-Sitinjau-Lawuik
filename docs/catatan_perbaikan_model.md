# Catatan Teknis Perbaikan Model & Visualisasi Bounding Box (Sitinjau Lauik)

Dokumentasi riwayat investigasi dan perbaikan anomali visual pada deteksi kendaraan (halaman `/dev`).

---

## 1. Gejala Permasalahan yang Ditemukan
Terdapat tiga anomali visual pada overlay bounding box di mode pengembang:
1. **Berkedip (*Flicker*)**: Kotak deteksi menyala-mati secara berkala pada objek yang sama.
2. **Dobel (*Ghosting*)**: Satu unit kendaraan memiliki dua bounding box sekaligus.
3. **Melayang (*Drifting*)**: Kotak deteksi terpisah dari kendaraan dan tampak melayang menjauhi posisi fisik kendaraan.

---

## 2. Akar Masalah (*Root Cause*)
Sistem menerapkan mekanisme **Frame Skip** untuk efisiensi komputasi (`detect_every_n: 2` pada `config/settings.yaml`), yang berarti model YOLOv8 hanya dieksekusi setiap interval 2 frame, sedangkan frame sisanya tetap disalurkan ke video stream.

- **Penyebab Berkedip:**  
  Pada frame tanpa eksekusi YOLO (frame skip), thread pemrosesan sebelumnya memanggil `tracker.update([])`. Hal ini menyebabkan semua track terdaftar dianggap *miss*, sehingga overlay kotak menjadi kosong sesaat sebelum muncul kembali pada frame berikutnya.
- **Penyebab Melayang & Dobel:**  
  Ketika estimasi posisi Kalman Filter dipaksakan untuk digambar pada frame skip tanpa konfirmasi visual YOLO, vektor kovarians Kalman menyebabkan kotak bergeser mengikuti prediksi gerak linier. Saat deteksi YOLO berikutnya masuk dengan posisi berbeda, asosiasi Mahalanobis/IoU terpecah dan membuat ID baru, menghasilkan kotak ganda.

---

## 3. Solusi Arsitektural yang Diterapkan
1. **Overlay Hanya Menggambar Kotak Terkonfirmasi Visual:**  
   Hanya track dengan konfirmasi deteksi YOLO aktif (`frames_since_seen == 0` dan `age >= min_hits`) yang digambar pada kanvas visualisasi. Prediksi murni Kalman tidak digambar ke overlay layar.
2. **Isolasi Pembaruan Tracker pada Frame Skip:**  
   Tracker dan penghitung garis (*line counter*) tidak lagi diperbarui dengan deteksi kosong (`update([])`) pada frame skip. State pelacakan dipertahankan secara stabil.
3. **Frame Retention (Hold Box):**  
   Pada frame skip, bounding box dari deteksi terakhir dipertahankan pada koordinatnya di atas video frame terbaru tanpa interpolasi melayang.
