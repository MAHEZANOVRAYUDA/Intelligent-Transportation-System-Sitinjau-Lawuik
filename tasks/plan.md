# Implementation Plan: Pemisahan Stream Bersih vs Dev, Perbaikan Pipeline Realtime Counting, & Eliminasi Celah Sistem

## 1. Ringkasan Eksekutif & Analisis Akar Masalah (Root Cause Analysis)

Berdasarkan audit mendalam terhadap seluruh arsitektur sistem (Edge Node `main_edge.py`, Backend Ingestion FastAPI `src/api/main.py`, Dev Routes `src/api/routes/dev.py`, Engine PKJI `src/analytics/density.py`, Database SQLite `src/storage/database.py`, serta Frontend `static/dashboard/` dan `static/dev/`), berikut adalah identifikasi akar masalah dan penyebab teknisnya:

---

### 1.1 Masalah 1: Dashboard Utama Menampilkan Bounding Box AI
* **Gejala**: Tampilan video di Dashboard Gerbang (`/gerbang`) menampilkan kotak deteksi bounding box, label kelas, tracker ID, dan garis counting, sama persis seperti pada menu Dev (`/dev`). Padahal kebutuhan dashboard operasional/publik adalah **video feed CCTV murni (clean RTSP feed)** tanpa ornamen teknis AI.
* **Akar Masalah Teknis**:
  1. Pada `.env`, `GATE_A_MODE=edge` aktif. Di mode ini, server laptop/VPS mem-proxy streaming video dari Raspberry Pi 5 melalui `_proxy_edge_stream` (`http://<edge_ip>:8080/stream`).
  2. Di sisi Edge (`main_edge.py`), thread pemrosesan hanya menghasilkan satu frame terkompresi yaitu frame yang sudah digambar anotasi (`annotated = annotate_frame(...)`) dan dimasukkan ke satu-satunya buffer `stream_holder`.
  3. Server web internal Edge (`EdgeHTTPHandler`) hanya mengekspos satu endpoint `/stream` yang menyajikan frame teranotasi tersebut.
  4. Server pusat FastAPI mem-proxy endpoint yang sama (`/stream`) baik untuk rute publik `/api/stream/{gate_id}` maupun rute pengembang `/api/dev/stream/{gate_id}`.
  5. Akibatnya tidak ada pemisahan kanal stream antara kebutuhan Dashboard Operasional (Clean) dan Dev Dashboard (AI Overlays).

---

### 1.2 Masalah 2: Angka Counting Kendaraan Tidak Muncul di Dashboard dan Dev (Tetap 0)
* **Gejala**: Meskipun pada overlay video Dev Mode (Screenshot 3) terlihat bahwa tracking dan counting di Edge berjalan (`IN: M:0 C:92 B:17 T:3 | OUT: M:0 C:66 B:8 T:0`), angka pada kartu metrik Dashboard Utama (Screenshot 2: `ARUS KENDARAAN 0 smp/jam`, `KENDARAAN HARI INI 0 unit`) dan kartu metrik Dev Mode tetap bernilai 0 / `--`.
* **Akar Masalah Teknis (Putusnya 4 Rantai Pipeline Data)**:
  1. **Edge Heartbeat Mengabaikan Breakdown Kelas**:
     Di `main_edge.py` (`_start_heartbeat_worker`), Edge hanya menghitung total integer skalar:
     `total_in = sum(self.counter.state.total_in.values())`
     Rincian dictionary per kelas (`motor`, `mobil`, `bus`, `truck`) **tidak pernah dikirimkan** dalam payload detak jantung (heartbeat).
  2. **Celah Kritis Ingestion Server (`/api/lapor-lalin`) Membuang Data**:
     Di `src/api/main.py` (`terima_lapor_lalin`), ketika Edge mengirim akumulasi per 5 menit:
     Fungsi tersebut menghitung bobot EKR dan derajat kejenuhan DS untuk kebutuhan logging, namun **SAMA SEKALI TIDAK PERNAH** memanggil `save_crossing()` ke database SQLite (`sitinjau_laut.db`), dan **TIDAK PERNAH** memanggil `state.occupancy_manager.register_entry()` / `register_exit()`. Data yang diterima langsung dibuang begitu respons HTTP dikembalikan!
  3. **Snapshot Server Tidak Menggabungkan Data Edge**:
     Di `src/api/main.py` (`_build_current_snapshot`):
     `snap["gate_counts"] = state.detection_worker.get_counter_stats()`
     Karena Gerbang A berjalan dalam mode Edge, `state.detection_worker` lokal server tidak memproses Gerbang A, sehingga `gate_counts["A"]` selalu bernilai kosong/0. Data hitungan dari `state.edge_nodes` tidak pernah di-merge ke dalam `snap["gate_counts"]`.
     Selain itu, `snap["today_crossings"]` membaca tabel `crossings` di database SQLite yang selamanya kosong karena poin (2).
  4. **Contract Mismatch di Endpoint Dev Mode (`/api/dev/state/{gate_id}`)**:
     Di `src/api/routes/dev.py`, untuk mode Edge:
     - Field `classes` di-hardcode ke 0: `"classes": {"motor": 0, "mobil": 0, "bus": 0, "truck": 0}`.
     - Endpoint mengembalikan key `"total_in"` dan `"total_out"`, padahal JavaScript di `static/dev/index.html` mengharapkan objek dictionary `counts_in: {motor, mobil, bus, truck}` dan `counts_out: {motor, mobil, bus, truck}`. Akibatnya tabel rincian di Dev Mode selalu menampilkan nilai kosong/0.

---

### 1.3 Audit Celah Arsitektur, Backend, API, Database, & Frontend
1. **Latensi Sinkronisasi 5 Menit Terlalu Lambat**:
   Jika hanya mengandalkan interval 5 menit `/api/lapor-lalin`, angka di dashboard akan diam selama 5 menit lalu melompat tiba-tiba. Solusinya: sinkronisasi realtime melalui heartbeat berkala (3-5 detik) dengan mekanisme **Delta Processing** (menghitung selisih pertambahan kendaraan terkini dibanding hitungan sebelumnya) sehingga database dan engine PKJI ter-update secara instan.
2. **Duplikasi Koneksi RTSP**:
   Kamera CCTV IP (seperti Bardi / Onvif) memiliki keterbatasan sesi koneksi RTSP simultan (biasanya maksimal 2 klien). Jika server pusat dan edge sama-sama membuka RTSP ke IP kamera yang sama, kamera dapat menolak koneksi atau mengalami packet drop. Karena itu, Edge Node yang berada di dekat CCTV bertindak sebagai **Primary Ingestor** dan mendistribusikan frame (clean & dev) ke server pusat melalui HTTP MJPEG.
3. **Stuck Video Placeholder di Frontend**:
   Di `gerbang.html`, jika `img.onerror` terpicu sesaat saat koneksi RTSP sedang inisialisasi, status bisa tertahan pada overlay *“Menghubungkan ke CCTV Gerbang A... Mohon tunggu”*. Perlu dipastikan handler stream otomatis me-reset tampilan begitu frame MJPEG pertama tiba.

---

## 2. Arsitektur Solusi & Alur Data Baru (Target Architecture)

```
[ CCTV RTSP Stream ]
         │
         ▼
[ main_edge.py (RPi 5 / Edge Runner) ]
   ├── Frame Asli (Clean) ──────────> EdgeStreamHolder.raw_jpeg ───────> GET /stream (Clean Feed)
   │
   ├── AI Inference & Tracking
   │     │
   │     ├── Annotated Frame ───────> EdgeStreamHolder.dev_jpeg ───────> GET /stream/dev (Dev Feed)
   │     │
   │     └── Virtual Counting ──────> counts_in / counts_out (per kelas)
   │                                        │
   │                                        ├── Heartbeat Tiap 5 Detik (Realtime Counts)
   │                                        └── Interval Lapor Tiap 5 Menit (Audited Accumulation)
                                                    │
                                                    ▼
                                   [ Server Pusat FastAPI (main.py) ]
                                      ├── /api/stream/{gate_id}      --> Proxy /stream (Clean)
                                      ├── /api/dev/stream/{gate_id}  --> Proxy /stream/dev (Annotated)
                                      │
                                      ├── Heartbeat / Lapor Ingestion:
                                      │     ├── Hitung Delta Kendaraan
                                      │     ├── save_crossing() ke SQLite (crossings table)
                                      │     ├── occupancy_manager.register_entry/exit() (PKJI engine)
                                      │     └── Update state.edge_nodes (counts_in, counts_out)
                                      │
                                      └── _build_current_snapshot():
                                            ├── Merge edge counts_in & counts_out ke snap["gate_counts"]
                                            ├── today_crossings membaca data riil dari SQLite
                                            └── Broadcast via WebSocket ke seluruh Dashboard & Dev UI
```

---

## 3. Rencana Kerja Terstruktur (Vertical Slices & Tasks)

### Task 1: Dual-Stream Buffer & Web Server Duplex di Edge Runner
- **Target File**: `main_edge.py`
- **Rincian Perubahan**:
  1. Modifikasi `EdgeStreamHolder` agar menyimpan dua buffer frame terpisah:
     - `_clean_jpeg`: Frame asli CCTV (hanya di-resize ke resolusi transmisi, zero annotations).
     - `_annotated_jpeg`: Frame hasil render AI (`annotate_frame`) dengan bounding box, tracker ID, garis counting, dan FPS.
  2. Perbarui `EdgeHTTPHandler`:
     - Rute `GET /stream`: Menghantarkan MJPEG dari frame bersih (`_clean_jpeg`).
     - Rute `GET /stream/dev`: Menghantarkan MJPEG dari frame teranotasi AI (`_annotated_jpeg`).
  3. Modifikasi perulangan inferensi di `_run_loop`:
     - Encode frame asli menjadi `_clean_jpeg`.
     - Encode frame hasil `annotate_frame` menjadi `_annotated_jpeg`.
  4. Perbarui payload heartbeat pada `_start_heartbeat_worker`: kirim dictionary lengkap `counts_in` dan `counts_out` per kelas (`motor`, `mobil`, `bus`, `truck`), bukan hanya nilai integer sum.
- **Acceptance Criteria**:
  - `http://<edge-ip>:8080/stream` menyajikan video CCTV bersih tanpa bounding box.
  - `http://<edge-ip>:8080/stream/dev` menyajikan video CCTV lengkap dengan bounding box dan visual tracking.
  - Heartbeat mengirimkan breakdown per-kelas kendaraan.
- **Verifikasi**: Jalankan `pytest tests/test_main_edge.py -v`.

---

### Task 2: Sinkronisasi Schema Data Kontrak API & Heartbeat
- **Target Files**:
  - `src/edge/sync_client.py`
  - `src/api/main.py`
- **Rincian Perubahan**:
  1. Di `src/edge/sync_client.py`:
     - Perbarui signature `send_heartbeat` untuk menerima `counts_in: dict[str, int]` dan `counts_out: dict[str, int]`.
     - Kirim field tersebut dalam payload JSON ke server.
  2. Di `src/api/main.py`:
     - Perbarui model Pydantic `EdgeHeartbeatPayload`:
       `counts_in: dict[str, int] = Field(default_factory=dict)`
       `counts_out: dict[str, int] = Field(default_factory=dict)`
     - Normalisasi payload agar tetap kompatibel jika node lama mengirim integer atau dictionary.
- **Acceptance Criteria**:
  - Endpoint `/api/edge/heartbeat` menerima dan memvalidasi payload berisi rincian kelas masuk dan keluar secara type-safe.
- **Verifikasi**: Unit test endpoint heartbeat dengan payload dictionary per-kelas.

---

### Task 3: Ingestion Engine, Delta Synchronization, & Persistensi Database
- **Target File**: `src/api/main.py`
- **Rincian Perubahan**:
  1. Buat helper fungsi ingestion delta `_process_edge_vehicle_deltas(gate_id, counts_in, counts_out)`:
     - Bandingkan hitungan kumulatif terbaru dengan hitungan yang sudah tercatat sebelumnya (`last_processed_counts`).
     - Untuk setiap penambahan kendaraan ($\Delta > 0$):
       - Simpan ke database SQLite menggunakan `save_crossing()` untuk masing-masing kelas.
       - Daftarkan ke `state.occupancy_manager`:
         - Jika arah IN: panggil `register_entry(class_name, gate=gate_id, direction="menanjak" if gate_id=="A" else "menurun")`.
         - Jika arah OUT: panggil `register_exit(class_name, gate=gate_id, direction="menurun" if gate_id=="A" else "menanjak")`.
     - Perbarui catatan `last_processed_counts`.
  2. Panggil fungsi ingestion delta ini pada:
     - Handler `edge_heartbeat` (pembaruan cepat tiap beberapa detik).
     - Handler `terima_lapor_lalin` (audit interval 5 menit).
  3. Perbarui `_build_current_snapshot()`:
     - Jika gerbang beroperasi dalam mode Edge, masukkan data `counts_in` dan `counts_out` dari `state.edge_nodes[gid]` ke dalam `snap["gate_counts"][gid]`.
- **Acceptance Criteria**:
  - Setiap kendaraan yang terhitung di Edge otomatis tersimpan ke tabel `crossings` di database SQLite.
  - `state.occupancy_manager` terisi secara realtime, menghasilkan nilai $Q$ (smp/jam) dan Derajat Kejenuhan ($DS$) yang akurat.
  - Snapshot monitoring menyertakan `gate_counts` lengkap untuk Gerbang A dan Gerbang B.
- **Verifikasi**: Endpoint `/api/monitoring/current` mengembalikan `today_crossings` $> 0$, `volume_q_smp_jam` $> 0$, dan `gate_counts` berisi data gerbang edge.

---

### Task 4: Pemisahan Routing Stream & Pembaharuan Dev State API
- **Target Files**:
  - `src/api/main.py`
  - `src/api/routes/dev.py`
- **Rincian Perubahan**:
  1. Di `src/api/main.py`:
     - Rute `/api/stream/{gate_id}` (digunakan oleh Dashboard dan Gerbang):
       - Untuk mode Edge, panggil `_proxy_edge_stream(gate_id, endpoint="/stream")` (mengambil feed bersih).
       - Untuk mode lokal, panggil `_mjpeg_generator(gate_id)` (feed bersih).
  2. Di `src/api/routes/dev.py`:
     - Rute `/api/dev/stream/{gate_id}` (digunakan khusus oleh Dev Dashboard):
       - Untuk mode Edge, panggil `_proxy_edge_stream(gate_id, endpoint="/stream/dev")` (mengambil feed beranotasi AI).
       - Untuk mode lokal, panggil `_dev_mjpeg_generator(gate_id)` (feed beranotasi AI).
     - Rute `/api/dev/state/{gate_id}`:
       - Kembalikan `counts_in` dan `counts_out` riil dari `state.edge_nodes[gid]`.
       - Hilangkan hardcode 0 pada `classes`, petakan dari total masuk + keluar per kelas.
- **Acceptance Criteria**:
  - Dashboard utama (`/gerbang`) 100% bebas dari bounding box deteksi.
  - Dev dashboard (`/dev`) menampilkan video dengan bounding box dan tabel angka counting terisi secara sinkron.
- **Verifikasi**: Verifikasi visual browser & test respons JSON `/api/dev/state/{gate_id}`.

---

### Task 5: Optimasi Tampilan Frontend Dashboard & Gerbang
- **Target Files**:
  - `static/dashboard/gerbang.html`
  - `static/dashboard/index.html`
  - `static/dev/index.html`
- **Rincian Perubahan**:
  1. Di `static/dashboard/gerbang.html`:
     - Pastikan pemanggilan stream tetap ke `/api/stream/{gateId}` (yang kini bersih).
     - Perbaiki transisi dari placeholder ke live video pada event `onload` elemen `<img>` agar tidak tertahan menampilkan teks “Menghubungkan...”.
     - Verifikasi binding data metrik 4 kelas kendaraan (Mobil Penumpang, Truk, Bus, Motor) dari `gate_counts`.
  2. Di `static/dashboard/index.html`:
     - Verifikasi pembaruan angka metrik utama:
       - Arus Kendaraan ($Q$ smp/jam).
       - Kendaraan Hari Ini (unit).
       - Rekapitulasi Masuk / Keluar per kelas.
  3. Di `static/dev/index.html`:
     - Pastikan tabel hitungan membaca `counts_in` dan `counts_out` dari respon `/api/dev/state/{gate_id}` dengan benar.
- **Acceptance Criteria**:
  - Tampilan dashboard tidak menampilkan error console, kartu metrik menampilkan angka aktual, dan video CCTV tampil jernih.

---

### Task 6: Regresi & Validasi Pengujian Menyeluruh
- **Target Files**:
  - `tests/test_main_edge.py`
  - `tests/test_pkji_api.py`
  - `tests/test_database.py`
  - Seluruh file uji lainnya
- **Rincian Perubahan**:
  1. Tambahkan unit test untuk:
     - Dual-stream endpoint di Edge.
     - Penerimaan heartbeat dengan payload breakdown kelas.
     - Ingestion delta ke database dan occupancy manager.
     - Pemisahan proxy clean stream vs dev stream di server FastAPI.
  2. Jalankan seluruh suite test dengan `pytest` dan pastikan 100% lulus (65+ tests).
- **Acceptance Criteria**:
  - Semua unit test & integration test lolos tanpa error maupun regression.
