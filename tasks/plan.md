# Implementation Plan: Sinkronisasi Dev Gerbang A & B, Kalibrasi Garis Full-Span Bardi, Eliminasi Double Lines, & Edge Hardening

## 1. Ringkasan Eksekutif & Analisis Akar Masalah (Root Causes)

Berdasarkan inspeksi tangkapan layar Pengguna (Gambar 1, 2, dan 3) serta audit mendalam pada codebase frontend (`static/dev/index.html`) dan backend (`src/`), ditemukan 4 akar masalah teknis:

### 1.1 Masalah 1: Bug Frame Tertimpa saat Beralih Gerbang (Gate Switching Stale Frame)
- **Gejala (Gambar 1)**: Ketika beralih dari Gerbang A ke B, lalu kembali ke Gerbang A, video kamera Gerbang B tetap tampil membeku di latar belakang dengan garis koordinat Gerbang A tergambar di atasnya, disertai teks *"Menghubungkan ke CCTV GERBANG A..."*.
- **Akar Masalah**: Elemen HTML native `<img id="dev-stream">` tidak menghapus buffer frame grafis lama saat atribut `src` diubah ke endpoint baru (`/api/dev/stream/A`). Karena kamera Gerbang A belum terhubung/offline, browser menahan frame terakhir dari Gerbang B. Pada saat bersamaan, `fetchGateState('A')` berhasil mengambil koordinat Gerbang A dan me-render garis Gerbang A di atas gambar beku Gerbang B.
- **Solusi**: Pada fungsi `switchGate(gateId)` di `static/dev/index.html`:
  1. Bersihkan canvas overlay seketika (`ctx.clearRect`).
  2. Sembunyikan frame lama dengan menyetel `img.style.opacity = '0'` atau reset `src` ke placeholder kosong saat inisiasi pergantian.
  3. Tampilkan kartu loading/offline berstandar UI elegan (`#video-offline`) yang menutupi area video sampai stream baru benar-benar mengirim frame pertama (`img.onload`).
  4. Hanya tampilkan gambar kembali (`img.style.opacity = '1'`) setelah event `onload` frame baru terverifikasi.

---

### 1.2 Masalah 2: Garis Kalibrasi Gerbang B Terpotong & Tidak Full-Span pada Kamera Bardi
- **Gejala (Gambar 2)**: Garis merah (counting) Gerbang B hanya muncul pendek di bagian atas (`[100, 400, 900, 400]`), sedangkan garis biru/cyan (lajur) tidak presisi atau bocor dari Gerbang A.
- **Akar Masalah**:
  1. Di `config/settings.yaml`, koordinat default Gerbang B di-hardcode ke nilai sempit `[100, 400, 900, 400]`, padahal kamera CCTV Bardi memiliki resolusi native `2560×1440` (atau `2304×1296`).
  2. Gerbang B tidak memiliki konfigurasi `lane_divider` default di `settings.yaml`. Akibatnya saat beralih ke Gerbang B, variabel `draftLane` di JavaScript tidak diperbarui dan tetap menyimpan koordinat garis lajur milik Gerbang A (`leakage state`).
  3. Endpoint `dev_state("B")` di `src/api/routes/dev.py` tidak mengembalikan `frame_width` dan `frame_height`, sehingga rumus transformasi skala `frameToCanvas()` di frontend mengasumsikan resolusi yang salah.
- **Solusi**:
  1. Konfigurasi koordinat Gerbang B di `config/settings.yaml` agar membentang **penuh 100% layar** (*full-width* horizontal untuk counting: `[0, 854, 2559, 854]`, dan *full-height* vertikal untuk pemisah lajur: `[1150, 0, 1150, 1439]`).
  2. Pastikan `dev_state("B")` selalu mengembalikan `frame_width: 2560`, `frame_height: 1440`, serta nilai `lane_divider` dan `inbound_side` yang valid.
  3. Di JavaScript, jika `data.lane_divider` bernilai `null`, `draftLane` secara eksplisit disetel ke `null` (tidak mewarisi sisa gerbang sebelumnya).

---

### 1.3 Masalah 3: Efek Garis Ganda (*Double Lines Artifact*) & Visual Clutter
- **Gejala (Gambar 1 & 2 vs Gambar 3)**: Pada Gambar 1 dan 2 tampak garis merah ganda dan teks `COUNTING LINE` tercetak kaku di dalam video. Padahal pada Gambar 3 (tampilan ideal yang diinginkan pengguna), garis counting merah dan lajur cyan tampil sangat rapi, bersih, tanpa teks burned-in yang menumpuk.
- **Akar Masalah**: Modul backend `annotate_frame` (`src/detection/visualizer.py`) menggambar garis merah dan cyan langsung ke dalam piksel JPEG video. Pada saat yang sama, elemen `<canvas id="line-canvas">` di frontend menggambar garis kalibrasi interaktif di atasnya. Saat ada perbedaan resolusi atau saat garis digeser, timbul efek bayangan ganda (*ghosting*).
- **Solusi**:
  1. Tambahkan parameter `draw_lines: bool = False` pada `annotate_frame` untuk stream mode `/dev`.
  2. Alirkan video bersih dengan bounding box deteksi kendaraan ke frontend, dan biarkan `<canvas id="line-canvas">` menangani rendering garis virtual 2 arah secara visual interaktif persis seperti Gambar 3.

---

### 1.4 Masalah 4: Edge Hardening & Dependensi Bebas Error pada Raspberry Pi 5 (Hailo-8L)
- **Kondisi**: Pengguna ingin seluruh persiapan kode di laptop tuntas malam ini sehingga konektor laptop-ke-Raspberry Pi dan Hailo terhubung sempurna, lalu besok script tinggal dijalankan di Raspberry Pi tanpa kendala dependensi atau permission.
- **Temuan Dependensi**: File `requirements-edge.txt` belum mencantumkan `scipy`, padahal algoritma asosiasi Hungarian di `src/detection/tracker.py` mengimpor `from scipy.optimize import linear_sum_assignment`. Jika tidak ditambahkan, script edge akan melempar `ModuleNotFoundError: No module named 'scipy'`.
- **Solusi**:
  1. Lengkapi `requirements-edge.txt` dengan `scipy>=1.11.0`.
  2. Pastikan `main_edge.py` menyalakan web streaming port 8080 secara default dan menangani gracefully reconnect kamera RTSP Bardi.
  3. Sediakan panduan eksekusi terminal satu perintah yang mudah dan aman untuk pengguna jalankan di Raspberry Pi besok.

---

## 2. Rencana Pelaksanaan Bertahap (Vertical Slice Tasks)

### Task 1: Konfigurasi Full-Span Gerbang B & Sinkronisasi API State
- **Tujuan**: Memastikan koordinat garis merah dan cyan Gerbang B membentang penuh di kamera Bardi (`2560×1440`) dan API mengembalikan metadata resolusi yang tepat.
- **Target Files**:
  - `config/settings.yaml`
  - `src/api/routes/dev.py`
- **Rincian Perubahan**:
  1. Di `config/settings.yaml`, perbarui Gerbang B:
     ```yaml
     counting_line: [0, 854, 2559, 854]
     entry_direction: down
     lane_divider: [1150, 0, 1150, 1439]
     inbound_side: left
     ```
  2. Di `src/api/routes/dev.py`, perbarui endpoint `dev_state("B")` agar menyertakan:
     - `frame_width: 2560`
     - `frame_height: 1440`
     - Nilai fallback `lane_divider` dan `inbound_side` dari `settings.yaml`.
- **Acceptance Criteria**:
  - `GET /api/dev/state/B` menghasilkan JSON dengan `counting_line` penuh `[0, 854, 2559, 854]`, `lane_divider: [1150, 0, 1150, 1439]`, serta `frame_width: 2560, frame_height: 1440`.
- **Verifikasi**: `pytest tests/test_dev_gates.py -v`.

---

### Task 2: Eliminasi Double Lines pada Visualizer & Stream Edge
- **Tujuan**: Menghilangkan garis burned-in kaku di dalam piksel JPEG sehingga hanya garis interaktif canvas beresolusi tajam yang tampil (standar Gambar 3).
- **Target Files**:
  - `src/detection/visualizer.py`
  - `main_edge.py`
  - `src/worker/detection_worker.py`
- **Rincian Perubahan**:
  1. Di `src/detection/visualizer.py`:
     - Tambahkan flag `draw_lines: bool = True` pada `annotate_frame`.
     - Ketika `draw_lines=False`, jangan gambar `draw_counting_line` dan `draw_lane_divider` ke frame (hanya gambar kotak deteksi, track, dan status HUD ringkas).
  2. Di `src/worker/detection_worker.py`:
     - Panggil `annotate_frame(..., draw_lines=False)` untuk feed debug `/dev`.
  3. Di `main_edge.py`:
     - Panggil `annotate_frame(..., draw_lines=False)` untuk feed web stream port 8080.
- **Acceptance Criteria**:
  - Frame JPEG video yang dikirim ke browser tidak memiliki garis merah/cyan permanen yang bertumpuk dengan canvas.
  - Video bersih dengan bounding box deteksi kendaraan yang responsif.
- **Verifikasi**: Jalankan `pytest tests/test_main_edge.py -v`.

---

### Task 3: Pembenahan Frontend UI/UX, State Isolation, & Reset Transisi Gerbang
- **Tujuan**: Menghilangkan bug frame tertimpa saat berganti gerbang, memastikan isolasi state kalibrasi antar gerbang, dan menampilkan garis virtual 2 arah yang rapi persis seperti Gambar 3.
- **Target Files**:
  - `static/dev/index.html`
- **Rincian Perubahan**:
  1. Pada fungsi `switchGate(gateId)`:
     - Reset state kalibrasi: `draftLine = null; draftLane = null;`.
     - Bersihkan canvas seketika: `ctx.clearRect(0, 0, canvas.width, canvas.height);`.
     - Reset tampilan stream: set `img.style.opacity = '0'`, tampilkan `#video-offline` dengan pesan *"Menghubungkan ke CCTV GERBANG [A/B]..."*.
  2. Pasang event listener pada elemen `img`:
     - `img.addEventListener('load')`: Ketika frame pertama dari stream baru tiba, hilangkan `#video-offline`, buat `img.style.opacity = '1'`, panggil `resizeCanvas()` dan `drawOverlay()`.
     - `img.addEventListener('error')`: Tetap tampilkan `#video-offline` dengan indikasi offline.
  3. Pada fungsi `updateUI(data)`:
     - Terapkan pembaruan ketat untuk `draftLine` dan `draftLane`: jika data dari server tidak memiliki garis lajur atau bernilai `null`, set `draftLane = null` (cegah kebocoran koordinat dari Gerbang A ke Gerbang B).
     - Perbarui `frameSize` dengan `data.frame_width` dan `data.frame_height`.
  4. Penyempurnaan Rendering Canvas (Gambar 3 Standard):
     - Pastikan garis merah (counting) dan garis cyan (lajur) digambar dengan ketebalan dan warna perceptually uniform (`#ff453a` dan `#3dd6ff`).
     - Tampilkan label koordinat yang akurat di panel samping kanan (`counting: [...]`, `lajur: [...]`).
- **Acceptance Criteria**:
  - Transisi klik Gerbang A -> Gerbang B -> Gerbang A bersih 100%, tidak ada frame kamera B yang tertinggal di Gerbang A.
  - Garis kalibrasi Gerbang B membentang penuh dari ujung ke ujung video tanpa terpotong.
  - Tidak ada garis ganda yang tampak pada video.
- **Verifikasi**: Uji transisi antarmuka di browser dan jalankan test suite frontend.

---

### Task 4: Penguatan Dependensi & Konfigurasi Edge (Raspberry Pi 5 + Hailo-8L)
- **Tujuan**: Menjamin tidak ada error modul hilang (`scipy`), port stream 8080 aktif otomatis, dan izin akses `/dev/hailo0` selalu siap saat dijalankan besok di Raspberry Pi.
- **Target Files**:
  - `requirements-edge.txt`
  - `deployment/sitinjau-edge.service`
  - `scripts/setup_edge_service.sh`
  - `main_edge.py`
- **Rincian Perubahan**:
  1. Di `requirements-edge.txt`: Tambahkan `scipy>=1.11.0`.
  2. Di `deployment/sitinjau-edge.service`: Pastikan `ExecStart` menyertakan argumen `--web-stream`.
  3. Di `main_edge.py`: Buat argumen `--web-stream` aktif secara otomatis jika berjalan dalam mode service atau jika port 8080 tersedia.
  4. Periksa penanganan error rekoneksi RTSP dan pelepasan file descriptor `/dev/hailo0` saat service dihentikan (`SIGTERM`).
- **Acceptance Criteria**:
  - `requirements-edge.txt` memiliki semua dependensi yang dibutuhkan oleh tracker dan detector.
  - File service systemd siap dieksekusi tanpa modifikasi manual.
- **Verifikasi**: Jalankan validasi Python syntax check dan unit test `tests/test_main_edge.py`.

---

### Task 5: Pengujian Penuh (Full Regression Test Suite) & Panduan Raspberry Pi
- **Tujuan**: Memastikan seluruh 60+ unit test lulus (100% GREEN) dan memberikan panduan eksekusi ringkas untuk Raspberry Pi besok.
- **Target Files**:
  - Seluruh file test di `tests/`
- **Acceptance Criteria**:
  - `pytest -v` menghasilkan 100% PASSED (zero failures, zero errors).
  - Git working directory bersih dan ter-push ke GitHub repository.
- **Verifikasi**: Jalankan `pytest -v`.

---

## 3. Matriks Ketergantungan File

| File Target | Modifikasi Utama | Ketergantungan |
|---|---|---|
| `config/settings.yaml` | Koordinat full-span Gerbang B (`counting_line`, `lane_divider`) | `src/config.py` |
| `src/api/routes/dev.py` | Resolusi `frame_width`/`height` & fallback kalibrasi Gerbang B | `settings.yaml`, `state.py` |
| `src/detection/visualizer.py` | Parameter `draw_lines=False` untuk cegah double lines | `cv2`, `main_edge.py` |
| `static/dev/index.html` | Frame clearing on gate switch, opacity transition, isolated draft state | `dev.py`, WebSockets |
| `requirements-edge.txt` | Penambahan `scipy>=1.11.0` untuk tracker Hungarian algorithm | `tracker.py` |
| `deployment/sitinjau-edge.service` | Flag `--web-stream` pada ExecStart | `main_edge.py` |
| `main_edge.py` | Default web-stream & frame resolution metadata | `visualizer.py` |
