# Todo Checklist: Perbaikan Deteksi Kendaraan (Bounding Box), Eliminasi Error POC FFmpeg, & Optimasi Edge Pi 5

## Phase 1: Perbaikan Parser Output Tensor Hailo-8L & Guard Fallback
- [x] Task 1.1: Perbarui fungsi `_parse_hailo_output` di `src/detection/hailo_detector.py` agar polimorfik mendukung format resmi HailoRT NMS (list of 80 class detections per-class `[ymin, xmin, ymax, xmax, score]`) serta format tensor matriks 6-kolom.
- [x] Task 1.2: Perbaiki guard `detect()` di `src/detection/detector.py` agar memeriksa `self._hailo_detector.is_loaded`, sehingga fallback otomatis ke Ultralytics berfungsi jika NPU tidak siap.
- [x] Task 1.3: Buat unit test parsing output Hailo di `tests/test_hailo_detector.py` untuk menguji ekstraksi kendaraan dengan berbagai bentuk output tensor NPU.

## Phase 2: Eliminasi Error FFmpeg POC / RPS & Stream Hardening
- [x] Task 2.1: Perbarui `OPENCV_FFMPEG_CAPTURE_OPTIONS` di `main_edge.py` dan `src/capture/stream_manager.py` (ubah `reorder_queue_size;0` -> `reorder_queue_size;5`, tambahkan `max_delay;500000`, dan set `OPENCV_FFMPEG_LOGLEVEL=8`).
- [x] Task 2.2: Uji kestabilan capture options RTSP untuk memastikan stream berjalan tanpa spam POC error.

## Phase 3: Sinkronisasi Metrik Live Detection & Heartbeat Edge
- [x] Task 3.1: Tambahkan data live `detection_count` dan `track_count` pada heartbeat `main_edge.py`.
- [x] Task 3.2: Teruskan metrik tersebut di `src/api/routes/dev.py` pada respons `GET /api/dev/state/B` agar bilah status footer dev web sinkron.

## Phase 4: Verifikasi & Panduan Eksekusi Terminal Raspberry Pi
- [x] Task 4.1: Jalankan seluruh test suite otomatis (`pytest -v`) untuk memastikan 100% test lulus (65/65 PASSED).
- [x] Task 4.2: Lakukan commit & push perubahan ke branch `main`.
- [x] Task 4.3: Berikan instruksi langkah demi langkah yang presisi untuk dieksekusi di terminal Raspberry Pi 5.
