# Implementation Plan: Perbaikan Deteksi Kendaraan (Bounding Box), Eliminasi Error POC FFmpeg, & Optimasi Edge Pi 5

## 1. Ringkasan Eksekutif & Analisis Akar Masalah (Root Causes)

Berdasarkan analisis tangkapan layar Pengguna (Gambar 1: Dashboard Dev dan Gambar 2: Terminal Raspberry Pi 5) serta audit mendalam pada file `src/detection/hailo_detector.py`, `src/detection/detector.py`, dan `main_edge.py`, berikut adalah 3 akar masalah teknis utama:

---

### 1.1 Akar Masalah Utama: Bounding Box & Objek Kendaraan 0 (Tidak Terdeteksi)
Pada Gambar 1, overlay video menunjukkan:
- `DEV MODE | Gerbang B | Infer 28.5 FPS`
- `Deteksi: 0 | Track: 0`
- Mobil hitam dan kendaraan lain melintas di jalan tetapi **sama sekali tidak ada bounding box** dan tidak ada objek yang terhitung.

Penyebab teknis:
1. **Ketidakcocokan Format Output Tensor Hailo (`_parse_hailo_output`)**:
   Di `src/detection/hailo_detector.py`, fungsi parsing saat ini mengasumsikan tensor berdimensi 2D dengan jumlah kolom $\ge 6$:
   ```python
   data = np.squeeze(tensor)
   if data.ndim != 2 or data.shape[1] < 6:
       continue
   ```
   **Fakta Teknis Hailo Model Zoo**: Model resmi `yolov8n.hef` (arsitektur HailoRT Post-Process NMS) mengeluarkan struktur list/array berisi 80 kelas COCO (atau tensor per-class). Masing-masing kelas berisikan deteksi dengan format 5 nilai: `[ymin, xmin, ymax, xmax, score]`. Indeks kelas ditentukan oleh urutan kelas dalam list (`class_id = 0..79`), bukan kolom ke-6!
   Karena kode memvalidasi `data.shape[1] < 6`, seluruh keluaran model Hailo **diabaikan dan dibuang** pada setiap frame. Akibatnya `len(detections)` selalu bernilai 0.
2. **Bug Logika Fallback pada `VehicleDetector.detect`**:
   Di `src/detection/detector.py`:
   ```python
   if self._hailo_detector is not None and not self._hailo_detector.is_mock:
       return self._hailo_detector.detect(frame)
   ```
   Kondisi di atas hanya memeriksa apakah instance `self._hailo_detector` ada (`is not None`), tanpa memeriksa apakah NPU berhasil dimuat (`self._hailo_detector.is_loaded`). Jika inisialisasi Hailo gagal dan fallback Ultralytics aktif, kode tetap memanggil `HailoDetector.detect(frame)` yang selalu me-return `[]`. Ultralytics CPU/GPU tidak pernah dieksekusi.

---

### 1.2 Analisis Gambar 2: Terminal Raspberry Pi 5 (`sitinjau-gate-b`)
1. **Perintah `sudo ufw allow 8080/tcp` -> `sudo: ufw: command not found`**:
   - `ufw` (Uncomplicated Firewall) bukan paket bawaan default Raspberry Pi OS (Debian).
   - **Kondisi Aktual**: Port 8080 **sudah berfungsi dan terbuka secara default**, terbukti video streaming dari port 8080 Raspberry Pi 5 berhasil diterima dan ditampilkan dengan mulus di browser laptop pada Gambar 1 (28.9 FPS). Perintah ini tidak diperlukan.
2. **Log Error FFmpeg Berulang**:
   ```
   [OPENCV:FFMPEG:16] Could not find ref with POC 108
   [OPENCV:FFMPEG:16] Error constructing the frame RPS.
   ```
   - **Akar Masalah**: Kamera CCTV Bardi mengalirkan video H.264/H.265 dengan frame tipe B (bi-directional prediction). Di `main_edge.py`, opsi capture disetel ke:
     `OPENCV_FFMPEG_CAPTURE_OPTIONS = "rtsp_transport;tcp|fflags;nobuffer|flags;low_delay|reorder_queue_size;0|..."`
     Parameter `reorder_queue_size;0` memaksa decoder FFmpeg untuk tidak menampung frame dalam antrean reorder. Akibatnya frame referensi (POC - Picture Order Count) terlambat tiba, dan FFmpeg gagal menyusun RPS (Reference Picture Set), menghasilkan log error berulang.
   - **Solusi**: Ubah `reorder_queue_size;0` menjadi `reorder_queue_size;5` (toleransi 5 frame untuk menyusun referensi tanpa menambah delay terasa) serta sesuaikan `OPENCV_FFMPEG_LOGLEVEL` menjadi `8` (`AV_LOG_FATAL`).

---

### 1.3 Sinkronisasi Metrik HUD Bawah Video
Pada Gambar 1, bilah status di bawah video menampilkan `Kecepatan AI: 0.0 FPS` dan `Objek Terdeteksi: 0`, meskipun video overlay menampilkan `Infer 28.5 FPS`.
Hal ini terjadi karena endpoint `/api/dev/state/B` di Central Gateway Server belum meneruskan metrik live tracking/deteksi dari heartbeat Edge Node.

---

## 2. Rencana Pelaksanaan Bertahap (Vertical Slices)

### Task 1: Perbaikan Parser Output Tensor Hailo-8L & Optimasi Lifecycle Stream
- **Target Files**:
  - `src/detection/hailo_detector.py`
  - `src/detection/detector.py`
- **Rincian Perubahan**:
  1. Modifikasi `_parse_hailo_output` di `src/detection/hailo_detector.py` agar polimorfik mendukung:
     - Format resmi HailoRT NMS list-of-classes (80 kelas COCO, per-detection `[ymin, xmin, ymax, xmax, score]`).
     - Format tensor 2D/3D `[N, 6]` (`[ymin, xmin, ymax, xmax, score, class_id]`).
     - Normalisasi bounding box ke ukuran frame pixel dengan batas minimum area objek.
  2. Pertahankan session `InferVStreams` dan `network_group.activate` agar tidak dibuat dan dihancurkan ulang setiap frame (menghilangkan latensi alokasi DMA).
  3. Perbaiki guard di `src/detection/detector.py`:
     ```python
     if self._hailo_detector is not None and self._hailo_detector.is_loaded and not self._hailo_detector.is_mock:
         return self._hailo_detector.detect(frame)
     ```
- **Acceptance Criteria**:
  - `_parse_hailo_output` berhasil mengekstrak kendaraan (mobil, motor, bus, truk) baik dari format list 80-kelas maupun format tensor matriks 6-kolom.
  - Jika NPU tidak aktif, sistem otomatis berpindah ke Ultralytics dan tetap menghasilkan bounding box.
- **Verifikasi**: Unit test `pytest tests/test_detector_fallback.py -v`.

---

### Task 2: Eliminasi Error FFmpeg POC / RPS & Pembersihan Log Kamera RTSP
- **Target Files**:
  - `main_edge.py`
  - `src/capture/stream_manager.py`
- **Rincian Perubahan**:
  1. Perbarui `OPENCV_FFMPEG_CAPTURE_OPTIONS`:
     - Ganti `reorder_queue_size;0` menjadi `reorder_queue_size;5` (memungkinkan penyusunan B-frame tanpa lag).
     - Tambahkan `max_delay;500000`.
     - Setel `OPENCV_FFMPEG_LOGLEVEL=8` (`AV_LOG_FATAL`) untuk meredam pesan non-fatal frame recovery.
- **Acceptance Criteria**:
  - Stream RTSP Bardi berjalan lancar tanpa spam `Could not find ref with POC` pada log service `systemctl status sitinjau-edge`.
- **Verifikasi**: Jalankan `pytest tests/test_main_edge.py -v`.

---

### Task 3: Sinkronisasi Metrik Live Detection & Heartbeat Edge ke Dashboard Dev
- **Target Files**:
  - `main_edge.py`
  - `src/edge/sync_client.py`
  - `src/api/main.py`
  - `src/api/routes/dev.py`
- **Rincian Perubahan**:
  1. Di `main_edge.py`, sertakan `detection_count` dan `track_count` terkini dalam laporan heartbeat berkala.
  2. Di `src/api/main.py` dan `src/api/routes/dev.py`, simpan dan teruskan metrik `detection_count` dan `track_count` pada respons JSON `/api/dev/state/B`.
- **Acceptance Criteria**:
  - Bilah status di bawah video Gambar 1 menampilkan FPS live, jumlah deteksi live, dan track live yang sinkron dengan frame video.
- **Verifikasi**: Test endpoint API `/api/dev/state/B` dan heartbeat.

---

### Task 4: Panduan Operasional Terminal Raspberry Pi 5
- **Tujuan**: Menyiapkan panduan eksekusi terminal step-by-step yang jelas untuk pengguna jalankan di layar Raspberry Pi (Gambar 2).
- **Langkah yang dirumuskan**:
  1. Melakukan `git pull origin main` di Raspberry Pi setelah kode diperbaiki.
  2. Menjelaskan status `ufw` (mengapa `ufw` tidak perlu dipasang karena port 8080 sudah terbuka).
  3. Merestart layanan edge: `sudo systemctl restart sitinjau-edge`.
  4. Memeriksa status: `journalctl -u sitinjau-edge -n 25 -f`.

---

## 3. Matriks Risiko & Mitigasi

| Risiko | Dampak | Mitigasi |
|---|---|---|
| Chip NPU Hailo-8L terkunci oleh proses zombie (status 74) | Medium | Sediakan fallback otomatis ke Ultralytics YOLOv8 dan panduan `sudo fuser -k /dev/hailo0` |
| B-frame GOP kamera Bardi bervariasi | Low | `reorder_queue_size;5` memberikan fleksibilitas rekonstruksi GOP tanpa membebani latency |
