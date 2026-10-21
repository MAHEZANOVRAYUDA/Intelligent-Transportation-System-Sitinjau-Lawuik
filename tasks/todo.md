# Todo Checklist: Perbaikan Edge AI & Penambahan Fitur Gerbang B pada /dev

## Phase 1: Robust Edge Detector Fallback & Diagnostics
- [x] Task 1.1: Perbaiki `src/detection/hailo_detector.py` agar error status 74 (`HAILO_OUT_OF_PHYSICAL_DEVICES`) tidak mengaktifkan mock mode kosong, melainkan mencatat log diagnostik jelas (`sitinjau-edge.service` busy/locked) dan menandai status `_loaded = False`.
- [x] Task 1.2: Perbarui `src/detection/detector.py` agar saat inisialisasi Hailo gagal (atau device tidak tersedia), sistem secara otomatis melakukan graceful fallback ke Ultralytics YOLOv8 (CPU/NCNN) sehingga deteksi kendaraan tidak pernah bernilai 0 kosong.
- [x] Task 1.3: Perbarui `main_edge.py` untuk mendukung opsi auto-fallback aman dan log instruksi troubleshooting di Raspberry Pi.

## Phase 2: OpenCV/FFmpeg HEVC RTSP Stream Stabilization
- [x] Task 2.1: Perbarui konfigurasi RTSP capture options di `main_edge.py` dan `src/capture/stream_manager.py` dengan flag lengkap: `rtsp_transport;tcp|fflags;nobuffer|flags;low_delay|reorder_queue_size;0`.
- [x] Task 2.2: Terapkan penekanan log level OpenCV/FFmpeg internal (`cv2.setLogLevel(cv2.LOG_LEVEL_ERROR)`) agar pesan transisi referensi frame HEVC POC tidak membanjiri layar terminal.
- [x] Task 2.3: Tambahkan frame warmup di `main_edge.py` untuk mengabaikan frame terdistorsi sebelum I-frame pertama terdekode utuh.

## Phase 3: Backend Multi-Gate Dev Worker Support
- [x] Task 3.1: Modifikasi `src/worker/detection_worker.py` agar selalu menginisialisasi `_counters`, `_trackers`, dan `_debug_states` untuk seluruh gerbang yang didefinisikan di `settings.yaml` (A dan B).
- [x] Task 3.2: Pastikan endpoint `GET /api/dev/state/{gate_id}` dan `POST /api/dev/calibrate/{gate_id}` mengembalikan data dan menyimpan konfigurasi garis Gerbang B dengan aman meskipun stream kamera sedang standby.

## Phase 4: Frontend UI/UX Gerbang B pada Halaman /dev
- [x] Task 4.1: Tambahkan antarmuka **Segmented Gate Switcher Control** (Gerbang A & Gerbang B) di bagian atas `static/dev/index.html` dengan desain konsisten berstandar tema Sitinjau Laut.
- [x] Task 4.2: Terapkan fungsi `switchGate(gateId)` di JavaScript untuk menangani perpindahan stream MJPEG `/api/dev/stream/{GATE}`, koneksi WebSocket `/api/dev/ws/{GATE}`, serta pembaruan judul dan metadata lokasi.
- [x] Task 4.3: Hubungkan pembacaan URL query parameter (`/dev?gate=b` atau `/dev?gate=a`) dan sinkronisasi browser URL tanpa reload.
- [x] Task 4.4: Hubungkan seluruh kontrol kalibrasi (garis counting merah & garis lajur cyan) agar memuat dan menyimpan koordinat spesifik Gerbang B ke `/api/dev/calibrate/B`.
- [x] Task 4.5: Tangani 6 UI States (Ideal, Loading, Error/Offline, Empty, Overflow, Optimistic) pada panel video dan kalibrasi.

## Phase 5: Verification & Automated Tests
- [x] Task 5.1: Buat unit test `tests/test_dev_gates.py` untuk memverifikasi endpoint state dan kalibrasi Gerbang B.
- [x] Task 5.2: Buat unit test simulasi fallback Hailo status 74 pada `VehicleDetector`.
- [x] Task 5.3: Jalankan seluruh test suite via `pytest` (memastikan 100% test lulus tanpa regresi - 55 passed).
