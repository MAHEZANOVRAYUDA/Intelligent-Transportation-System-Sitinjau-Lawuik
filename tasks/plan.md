# Implementation Plan: Perbaikan Edge AI (Hailo Status 74 & HEVC Stream) serta Penambahan Fitur Gerbang B pada /dev

## 1. Ringkasan Eksekutif & Analisis Akar Masalah

Berdasarkan analisis log terminal Raspberry Pi 5 pada Foto 1 dan Foto 2, serta inspeksi mendalam pada codebase server (`localhost:8000`), ditemukan 3 isu fundamental yang perlu diselesaikan secara terstruktur:

### 1.1 Analisis Masalah 1: Hailo NPU `HAILO_OUT_OF_PHYSICAL_DEVICES (74)` & Silent Zero-Count
- **Gejala (Foto 1 & 2)**:
  - `CHECK_SUCCESS failed with status=HAILO_OUT_OF_PHYSICAL_DEVICES(74)`
  - Saat Ctrl+C ditekan: `[DISPATCH] Mengirim akumulasi 5 menit (Total 0 unit): {'motor': 0, 'mobil': 0, 'bus': 0, 'truck': 0}`
- **Akar Masalah (Root Cause)**:
  1. Driver `libhailort` mengunci akses fisik PCIe `/dev/hailo0` secara eksklusif. Apabila service `sitinjau-edge.service` sudah aktif di background saat Raspberry Pi menyala, eksekusi manual kedua `python3 main_edge.py` akan ditolak oleh HailoRT dengan status 74.
  2. **Bug Silent Failure pada Kode**: Saat inisialisasi Hailo gagal karena status 74, `HailoDetector.load()` menangkap exception dan mengaktifkan `_mock_mode = True` lalu mengembalikan `True`. `VehicleDetector` mengira Hailo berhasil dimuat dan tidak melakukan fallback ke Ultralytics. Di dalam `detect()`, ketika `_mock_mode == True`, ia mengembalikan list kosong `[]`. Akibatnya, selama program berjalan kamera membaca gambar tetapi objek tidak pernah terdeteksi, berujung pada pengiriman `0 unit` ke server pusat.
- **Solusi**:
  1. Perbaiki `HailoDetector` dan `VehicleDetector`: Jika hardware NPU gagal diinisialisasi (misal status 74 atau device busy), sistem secara otomatis melakukan **Graceful Fallback** ke Ultralytics YOLOv8 (CPU/NCNN) dengan log peringatan yang jelas dan diagnostik troubleshooting (`sudo systemctl stop sitinjau-edge` / `fuser /dev/hailo0`).
  2. Tambahkan opsi otomatis fallback sehingga node edge di lapangan tidak pernah mengirim data kosong (0 unit) secara keliru.

---

### 1.2 Analisis Masalah 2: Spam Error OpenCV/FFmpeg HEVC (`Could not find ref with POC ... Error constructing the frame RPS`)
- **Gejala (Foto 1)**:
  - Terminal dipenuhi pesan error merah:
    `[hevc @ ...] Could not find ref with POC ...`
    `[hevc @ ...] Error constructing the frame RPS.`
- **Akar Masalah (Root Cause)**:
  - Kamera CCTV (Bardi PTZ) menyiarkan kompresi video H.265 / HEVC.
  - Saat stream RTSP dibuka, FFmpeg menerima paket video di tengah GOP (Group of Pictures) sebelum frame I (IDR/Keyframe) lengkap tiba. Tanpa frame referensi awal (SPS/PPS/IDR) atau saat ada jitter buffer, FFmpeg mencetak peringatan kehilangan referensi POC.
  - Setting `OPENCV_FFMPEG_CAPTURE_OPTIONS` belum dikonfigurasi lengkap dengan flag `fflags;nobuffer|flags;low_delay|reorder_queue_size;0`, dan log level FFmpeg belum diredam.
- **Solusi**:
  1. Standardisasi konfigurasi capture FFmpeg RTSP di `main_edge.py` dan `src/capture/stream_manager.py`.
  2. Konfigurasi `cv2.setLogLevel(cv2.LOG_LEVEL_ERROR)` dan filter log internal FFmpeg agar tidak membanjiri layar terminal saat menunggu I-frame pertama.
  3. Tambahkan warmup frame dropping (membuang 2-3 frame transisi pertama sampai decoder stabil).

---

### 1.3 Analisis Masalah 3: Halaman `/dev` Belum Mendukung Gerbang B
- **Kondisi Saat Ini**:
  - Di dashboard utama (`localhost:8000/gerbang?gerbang=b`), video Gerbang B sudah tampil dengan baik via `/api/stream/B`.
  - Di halaman developer `/dev` (`static/dev/index.html`):
    - Judul header di-hardcode: `Detection Debug — Gerbang A`.
    - Sumber gambar di-hardcode: `/api/dev/stream/A`.
    - Variabel JavaScript di-hardcode: `const GATE = 'A';`.
    - WebSocket dan endpoint kalibrasi hanya terhubung ke Gerbang A (`/api/dev/ws/A`, `/api/dev/calibrate/A`).
    - Belum ada segmented tab switcher untuk Gerbang B.
  - Di backend (`src/worker/detection_worker.py`):
    - `DetectionWorker` hanya menginisialisasi tracker dan counter untuk gerbang yang URL-nya aktif di registry, bukan semua gerbang di `settings.yaml`. Jika stream B lambat terkoneksi, request state atau kalibrasi untuk Gerbang B bisa gagal.
- **Solusi**:
  1. **Backend**: Pastikan `DetectionWorker` menginisialisasi state, counter, dan tracker untuk seluruh gerbang yang didefinisikan di `settings.yaml` (A dan B), sehingga `/api/dev/state/B` dan `/api/dev/calibrate/B` selalu siap diakses.
  2. **Frontend UI/UX (`static/dev/index.html`)**:
     - Tambahkan **Gate Switcher Control** (Gerbang A dan Gerbang B) dengan desain konsisten berstandar industri (sesuai palet tema gelap Sitinjau Laut).
     - Dukung navigasi dinamis via URL query parameter (`/dev?gate=b` atau `/dev?gate=a`).
     - Terapkan mekanisme reactive switch: mengalihkan image stream ke `/api/dev/stream/{GATE}`, menghubungkan WebSocket ke `/api/dev/ws/{GATE}`, memuat koordinat garis counting & pemisah lajur spesifik untuk gerbang aktif, dan mengeksekusi kalibrasi ke `/api/dev/calibrate/{GATE}`.
     - Tambahkan handling 6 UI states (Ideal, Loading, Error/Offline, Empty, Overflow, Optimistic) untuk stream video dan kalibrasi.

---

## 2. Rencana Pelaksanaan Bertahap (Vertical Slice Tasks)

### Task 1: Robust Edge Detector Fallback & Diagnostics (`src/detection/` & `main_edge.py`)
- **Tujuan**: Mengatasi error status 74 pada Hailo NPU dan mencegah silent failure (0 unit kendaraan terhitung).
- **Target Files**:
  - `src/detection/hailo_detector.py`
  - `src/detection/detector.py`
  - `main_edge.py`
- **Rincian Perubahan**:
  1. Di `hailo_detector.py`: Jika inisialisasi NPU gagal (khususnya status 74 `HAILO_OUT_OF_PHYSICAL_DEVICES`), set `_loaded = False`, `_mock_mode = False`. Cetak log diagnostik yang menginstruksikan pengguna bahwa `/dev/hailo0` terkunci oleh proses lain (misal `sitinjau-edge.service`) dan beri perintah `sudo systemctl stop sitinjau-edge`.
  2. Di `detector.py`: Jika inisialisasi backend Hailo gagal atau mengembalikan uninitialized device, jangan gunakan mock kosong. Lakukan auto-fallback ke Ultralytics YOLOv8 (CPU/NCNN) dengan log info ramah.
  3. Di `main_edge.py`: Tambahkan penanganan agar saat fallback aktif, proses counting tetap berjalan normal tanpa mengorbankan fungsionalitas lapangan.
- **Acceptance Criteria**:
  - Jika chip Hailo sibuk/terkunci (status 74), sistem tidak crash dan tidak menghasilkan 0 deteksi palsu, melainkan langsung beralih ke YOLOv8.
  - Muncul log diagnostik yang mengidentifikasi status bentrok hardware dengan jelas.
- **Verifikasi**: Buat unit test simulasi fallback Hailo status 74 di `tests/test_detector_fallback.py`.

---

### Task 2: Stabilisasi OpenCV/FFmpeg HEVC Stream Capture (`main_edge.py` & `src/capture/stream_manager.py`)
- **Tujuan**: Menghilangkan banjir error log merah `Could not find ref with POC ...` dan `Error constructing the frame RPS`.
- **Target Files**:
  - `main_edge.py`
  - `src/capture/stream_manager.py`
- **Rincian Perubahan**:
  1. Perbarui `OPENCV_FFMPEG_CAPTURE_OPTIONS` dengan opsi lengkap:
     `rtsp_transport;tcp|fflags;nobuffer|flags;low_delay|reorder_queue_size;0|analyzeduration;1000000|probesize;1000000`.
  2. Atur log level OpenCV/FFmpeg pada startup agar pesan transisi internal GOP tidak membanjiri terminal (`cv2.setLogLevel(cv2.LOG_LEVEL_ERROR)` dan `OPENCV_FFMPEG_LOGLEVEL=16`).
  3. Terapkan pembuangan 2-3 frame awal saat pembukaan stream untuk menunggu validasi I-frame pertama sebelum frame dikirim ke model deteksi.
- **Acceptance Criteria**:
  - Terminal bersih dari banjir pesan hevc POC error.
  - Video stream tersambung stabil melalui protokol TCP.
- **Verifikasi**: Jalankan uji koneksi stream lokal atau mock RTSP, pastikan inisialisasi capture tidak memunculkan log spam.

---

### Task 3: Backend Support Gerbang B pada Dev Worker & API (`src/worker/detection_worker.py`)
- **Tujuan**: Menjamin endpoint `/api/dev/stream/B`, `/api/dev/state/B`, dan `/api/dev/calibrate/B` selalu aktif dan dapat dikalibrasi.
- **Target Files**:
  - `src/worker/detection_worker.py`
  - `src/api/routes/dev.py`
- **Rincian Perubahan**:
  1. Di `DetectionWorker.start()`: Inisialisasi `_trackers`, `_counters`, dan `_debug_states` untuk SEMUA gerbang yang ada di `settings.yaml` (baik A maupun B).
  2. Pastikan `get_debug_state("B")` mengembalikan data konfigurasi garis default Gerbang B dari `settings.yaml` meskipun video feed belum aktif.
  3. Pastikan `apply_calibration("B", ...)` dapat menyimpan koordinat garis Gerbang B secara persisten ke `settings.yaml`.
- **Acceptance Criteria**:
  - Endpoint `GET /api/dev/state/B` mengembalikan JSON valid berisi koordinat garis Gerbang B.
  - Endpoint `POST /api/dev/calibrate/B` berhasil memperbarui dan menyimpan koordinat Gerbang B.
- **Verifikasi**: Tambahkan test API di `tests/test_dev_gates.py`.

---

### Task 4: Frontend UI/UX Gerbang B pada Halaman Dev (`static/dev/index.html`)
- **Tujuan**: Menyediakan antarmuka visual pemilihan gerbang (A/B), tampilan stream Gerbang B, dan kalibrasi garis interaktif untuk Gerbang B di `localhost:8000/dev`.
- **Target Files**:
  - `static/dev/index.html`
- **Rincian Perubahan**:
  1. Tambahkan **Segmented Gate Switcher Control** di bagian atas halaman `/dev`:
     - Tombol Gerbang A: `Gerbang A — Jl. Padang Besi (Kota Padang)`
     - Tombol Gerbang B: `Gerbang B — Jembatan Timbang (Solok)`
     - Desain tombol tab konsisten dengan `gerbang.html` dan standar tema gelap proyek.
  2. Implementasikan fungsi JavaScript `switchGate(gateId)`:
     - Mengubah state aktif (`currentGate = 'A'` atau `'B'`).
     - Menyinkronkan URL browser via `history.replaceState` (`/dev?gate=b`).
     - Memperbarui judul halaman, badge status gerbang, dan deskripsi lokasi.
     - Mengalihkan tag `<img id="dev-stream">` ke `/api/dev/stream/{GATE}` dengan timestamp query untuk cache-busting.
     - Menghentikan WebSocket lama dan membuat koneksi baru ke `/api/dev/ws/{GATE}`.
     - Memuat koordinat garis kalibrasi Gerbang B dari `/api/dev/state/B` dan me-render canvas overlay interaktif.
     - Menghubungkan seluruh tombol kalibrasi (`Terapkan`, `Simpan config`, `Reset counter`) ke endpoint `/api/dev/calibrate/{GATE}`.
  3. Dukungan 6 UI States:
     - Tampilan loading skeleton / placeholder saat berganti gerbang.
     - Tampilan offline / reconnecting jika kamera gerbang bersangkutan belum terhubung.
     - Respons kalibrasi real-time saat klik & drag garis virtual.
- **Acceptance Criteria**:
  - Pengguna dapat mengklik tab "Gerbang B" di `/dev` dan melihat stream Gerbang B.
  - Garis merah (counting) dan garis cyan (lajur) Gerbang B dapat digeser dan disimpan ke `settings.yaml`.
  - Halaman `/dev?gate=b` langsung membuka Gerbang B saat diakses atau di-refresh.
- **Verifikasi**: Uji fungsionalitas di browser atau subagent browser testing.

---

### Task 5: Validasi Komprehensif & Regression Test Suite
- **Tujuan**: Memastikan seluruh sistem berfungsi 100% tanpa ada regresi pada modul yang sudah ada.
- **Target Files**:
  - `tests/test_*.py`
- **Rincian Perubahan**:
  1. Jalankan seluruh unit test lama (49 tests).
  2. Jalankan unit test baru untuk fallback Hailo dan endpoint dev Gerbang B.
  3. Verifikasi linter dan sintaks Python serta validitas HTML/JS.
- **Acceptance Criteria**:
  - Seluruh test suite (50+ tests) berstatus **PASSED (100%)**.
  - Zero syntax error, zero console error di frontend dev.
- **Verifikasi**: Jalankan `pytest -v`.

---

## 3. Matriks File Target & Ketergantungan

| File Target | Modifikasi | Ketergantungan |
|---|---|---|
| `src/detection/hailo_detector.py` | Graceful failure reporting & diagnostic tips | `pyhailort` |
| `src/detection/detector.py` | Auto-fallback ke Ultralytics saat Hailo error | `hailo_detector.py`, `ultralytics` |
| `main_edge.py` | FFmpeg capture options, frame warmup, fallback support | `detector.py`, `cv2` |
| `src/capture/stream_manager.py` | FFmpeg TCP options & error suppression | `cv2` |
| `src/worker/detection_worker.py` | Multi-gate state initialization (A & B) | `settings.yaml`, `StreamRegistry` |
| `static/dev/index.html` | Segmented gate switcher, dynamic stream, interactive B-gate calibration | `dev.py`, WebSocket |
| `tests/test_dev_gates.py` | Unit tests untuk multi-gate dev endpoints | `pytest`, `TestClient` |
