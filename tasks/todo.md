# Todo Checklist: Pemisahan Stream Bersih vs Dev & Perbaikan Realtime Counting

- [x] **Task 1: Dual-Stream Buffer & Web Server Duplex di Edge Runner (`main_edge.py`)**
  - [x] Perluas `EdgeStreamHolder` untuk menampung `_clean_jpeg` dan `_annotated_jpeg`
  - [x] Update `EdgeHTTPHandler` untuk rute `GET /stream` (clean) dan `GET /stream/dev` (annotated)
  - [x] Di perulangan `_run_loop`, encode kedua frame secara efisien (frame bersih CCTV vs frame teranotasi AI)
  - [x] Di `_start_heartbeat_worker`, kirim rincian dictionary `counts_in` dan `counts_out` per kelas

- [x] **Task 2: Kontrak Schema API & Heartbeat Client-Server (`sync_client.py` & `main.py`)**
  - [x] Perbarui `EdgeSyncClient.send_heartbeat` di `src/edge/sync_client.py`
  - [x] Perbarui model Pydantic `EdgeHeartbeatPayload` di `src/api/main.py`
  - [x] Tambahkan validasi & backward-compatibility fallback pada schema

- [x] **Task 3: Ingestion Engine Delta, Database Persistence, & PKJI Occupancy (`main.py`)**
  - [x] Buat fungsi `_process_edge_vehicle_deltas()` untuk menghitung delta pertambahan kendaraan
  - [x] Panggil `save_crossing()` ke SQLite database untuk setiap unit kendaraan yang bertambah
  - [x] Panggil `register_entry()` dan `register_exit()` pada `state.occupancy_manager`
  - [x] Integrasikan delta processing di handler `/api/edge/heartbeat` dan `/api/lapor-lalin`
  - [x] Di `_build_current_snapshot()`, merge data hitungan edge ke `snap["gate_counts"]`

- [x] **Task 4: Pemisahan Routing Stream & Dev State Endpoint (`main.py` & `routes/dev.py`)**
  - [x] Konfigurasi `/api/stream/{gate_id}` agar mem-proxy stream bersih (`/stream`)
  - [x] Konfigurasi `/api/dev/stream/{gate_id}` agar mem-proxy stream beranotasi (`/stream/dev`)
  - [x] Perbarui respons `/api/dev/state/{gate_id}` dengan data `counts_in`, `counts_out`, dan `classes` riil

- [x] **Task 5: Optimasi Tampilan Frontend (`gerbang.html`, `index.html`, `dev/index.html`)**
  - [x] Pastikan transisi video feed di `gerbang.html` langsung menghilangkan placeholder saat feed terhubung
  - [x] Verifikasi binding data 4 kelas kendaraan di `gerbang.html`
  - [x] Verifikasi kartu metrik Arus Kendaraan dan Kendaraan Hari Ini di `index.html`
  - [x] Verifikasi tabel counter di `dev/index.html`

- [x] **Task 6: Pengujian Unit, Integrasi, & Verifikasi Browser (`pytest`)**
  - [x] Buat unit test untuk dual stream, heartbeat breakdown per kelas, dan delta ingestion
  - [x] Jalankan seluruh suite uji `pytest` (66 passed, 100% green)
  - [x] Update graphify knowledge graph
