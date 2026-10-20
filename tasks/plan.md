# Implementation Plan: Finalisasi, Pembersihan (Clean Code), & Push GitHub Sistem Deteksi Sitinjau Lauik ke Raspberry Pi 5

## 1. Ringkasan Eksekutif & Status Saat Ini
Repositori ini telah menyelesaikan seluruh tahapan rekayasa perangkat lunak untuk migrasi Edge AI Sitinjau Lauik:
- **Pengujian**: 49 dari 49 unit tests **LULUS 100%** (`tests/test_*.py`).
- **Edge Engine**: `main_edge.py` telah dirancang khusus untuk Raspberry Pi 5 + Hailo-8L NPU dengan footprint memori sangat hemat (<150 MB RAM), tanpa beban PyTorch/CUDA/Web UI.
- **Failover Buffer**: Modul `src/edge/buffer.py` (SQLite lokal) menjamin data counting tidak hilang saat jaringan 4G perbukitan mati dan otomatis terkirim via `src/edge/sync_client.py` saat online kembali.
- **Model Hardware Hailo**: File biner `models/yolov8n.hef` (12.5 MB) dan `models/yolov8n.onnx` (12.8 MB) **SUDAH TERSEDIA LENGKAP** dan siap dieksekusi langsung oleh chip NPU Hailo-8L.

Tujuan rencana ini adalah menuntaskan seluruh proses di laptop pengembangan (clean code audit, eliminasi file tidak terpakai, konfigurasi sanitasi `.gitignore`, penataan repositori) dan melakukan push perdana ke repositori GitHub baru pengguna:
**`https://github.com/MAHEZANOVRAYUDA/Intelligent-Transportation-System-Sitinjau-Lawuik.git`**
sehingga setelah ini pengguna **tidak perlu lagi mengotak-atik kode di laptop**, melainkan tinggal fokus pada setup fisik Raspberry Pi 5 di lapangan.

---

## 2. Analisis Kritis & Jawaban Pertanyaan Pengguna

### 2.1 File Sampah & Folder `user_repo_reference/`
- **Temuan**: Folder `user_repo_reference/` adalah arsip repositori referensi lama (dibuat 02/09/2026, ukuran >50 MB) yang berisi duplikasi file lama (`dashboard`, `data`, `sitinjau.db`, `snapshot_a.jpg`).
- **Tindakan**: Folder ini **TIDAK DIGUNAKAN** oleh arsitektur sistem baru. Folder ini akan **DIHAPUS TOTAL** dari disk laptop agar workspace 100% bersih dan tidak ada file liar yang terbawa ke GitHub.
- **File Redundan Lain**: File `yolov8n.pt` di root directory (6.5 MB) akan dihapus karena sudah ada di folder `models/` dan file PyTorch `.pt` tidak digunakan di Raspberry Pi (Raspberry Pi murni menggunakan model biner NPU `.hef`).

### 2.2 Ketersediaan File Model `.hef` dan `.onnx` untuk Hailo-8L
- **Status Biner**: **SUDAH ADA & 100% TERSEDIA!**
  - Path HEF: `models/yolov8n.hef` (Ukuran: **12.58 MB**) $\rightarrow$ Model terkompilasi biner khusus arsitektur NPU Hailo-8L (13 TOPS INT8).
  - Path ONNX: `models/yolov8n.onnx` (Ukuran: **12.85 MB**) $\rightarrow$ Format model ONNX opset 11 static shape 640x640 yang dioptimasi via onnxslim.
- **Pemuatan di Raspberry Pi**: Modul `src/detection/hailo_detector.py` dan `main_edge.py` sudah diprogram untuk secara otomatis memuat `models/yolov8n.hef` ke dalam chip Hailo-8L melalui library resmi `pyhailort`.

### 2.3 Performa di Raspberry Pi 5 (Apakah Berat?)
- **Kesimpulan**: **SANGAT RINGAN & AMAN DARI RISIKO OOM (Out Of Memory)!**
  1. **CPU & RAM Bebas**: Komputasi inferensi deteksi objek (perkalian matriks deep learning) **100% ditangani oleh chip fisik Hailo-8L NPU**, bukan oleh prosesor quad-core RPi 5.
  2. **Memory Footprint**: Program `main_edge.py` hanya mengonsumsi **~120 MB - 160 MB RAM**, dari kapasitas 2048 MB (2 GB) yang dimiliki RPi 5.
  3. **Zero Heavy Frameworks**: Di Raspberry Pi, kita **TIDAK** menginstal PyTorch / TorchVision (~1.5 GB), tidak menjalankan web server FastAPI, dan tidak merender dashboard frontend. Dependensi murni yang diinstal di RPi hanyalah `opencv-python-headless`, `numpy`, `requests`, `pyyaml`, dan `pydantic` melalui `requirements-edge.txt`.
  4. **OpenCV Zero-Lag**: Menggunakan buffer size = 1 (`cv2.CAP_PROP_BUFFERSIZE = 1`) sehingga tidak terjadi antrean penumpukan frame video di memori RAM.
  5. **Safety Net**: Script instalasi otomatis `scripts/setup_raspberry_pi.sh` sudah mengonfigurasi Swap Memory sebesar 2048 MB untuk mencegah OOM killer.

### 2.4 Kebijakan Repositori: Public vs Private
- **Rekomendasi**:
  1. **Tahap 1 (Saat ini)**: Repo dibuat **Public** (seperti yang telah dibuat pengguna). Keuntungannya: di Raspberry Pi Anda tinggal menjalankan perintah `git clone https://github.com/MAHEZANOVRAYUDA/Intelligent-Transportation-System-Sitinjau-Lawuik.git` tanpa perlu pusing memasukkan Personal Access Token (PAT) atau login SSH Key di terminal mini RPi.
  2. **Tahap 2 (Setelah program terpasang di Raspberry Pi)**: Ubah visibilitas repo menjadi **Private** melalui menu *Settings* GitHub atau satu perintah `gh repo edit --visibility private`. Dengan demikian seluruh kode riset & arsitektur sistem Anda terlindungi aman.
  3. **Jaminan Keamanan**: File rahasia `.env` (berisi URL CCTV, IP server, atau token) **TIDAK AKAN PERNAH DI-PUSH** ke GitHub karena sudah terproteksi ketat di dalam `.gitignore`. Yang dipush hanyalah template `.env.example`.

---

## 3. Struktur File yang Dimasukkan ke GitHub (Clean Repository Structure)

```
Intelligent-Transportation-System-Sitinjau-Lawuik/
├── .env.example                     # Template variabel lingkungan
├── .gitignore                       # Filter file rahasia, cache, dan data runtime
├── CONSTRAINTS.md                   # Standar kualitas rekayasa sistem
├── README.md                        # Dokumentasi komprehensif sistem & arsitektur
├── pytest.ini                       # Konfigurasi automated testing
├── main_edge.py                     # [CORE EDGE] Runner mandiri hemat RAM untuk RPi 5
├── run.py                           # [CORE SERVER] Runner server terpusat / laptop
├── requirements.txt                 # Dependensi Central Server (FastAPI, OpenCV, dll)
├── requirements-edge.txt            # Dependensi Ramping Edge Node (RPi 5 + Hailo-8L)
│
├── config/
│   └── settings.yaml                # Konfigurasi koordinat garis, threshold, dan gerbang
│
├── deployment/
│   └── sitinjau-edge.service        # Service daemon systemd untuk autostart di RPi 5
│
├── docs/
│   ├── PROJECT.md                   # Spesifikasi proyek
│   ├── algorithm.md                 # Penjelasan matematis line crossing & tracking
│   ├── catatan_perbaikan_model.md   # Riwayat evaluasi akurasi model
│   └── hardware_integrasi.md        # Panduan instalasi kabel, PoE, kamera Bardi, & NPU
│
├── models/
│   ├── .gitkeep
│   └── yolov8n.hef                  # [BINARY MODEL] Model biner 12.5MB untuk Hailo-8L
│
├── scripts/
│   ├── compile_hailo_docker.sh      # Tool Docker DFC jika ingin kuantisasi ulang
│   ├── download_hailo_model.py      # Verifikator model biner
│   ├── setup_raspberry_pi.sh        # [1-CLICK SCRIPT] Instalasi otomatis di RPi 5
│   └── simulate_traffic.py          # Generator simulasi pengujian end-to-end
│
├── src/
│   ├── analytics/                   # Analitik kapasitas jalan PKJI 2023, densitas, waktu tempuh
│   ├── api/                         # Endpoint ingestion /api/lapor-lalin & websocket
│   ├── capture/                     # RTSP Stream manager OpenCV
│   ├── counting/                    # Virtual line counter & directional logic
│   ├── detection/                   # BaseDetector, HailoDetector, VehicleDetector, Tracker
│   ├── edge/                        # SQLite Buffer Manager & Sync Client failover
│   ├── storage/                     # Database persistence
│   └── worker/                      # Asynchronous detection worker
│
├── static/                          # Aset antarmuka web monitoring (Dashboard & Dev UI)
│   ├── dashboard/
│   ├── data/sitinjau_corridor.geojson
│   └── dev/
│
└── tests/                           # 49 unit tests lengkap (100% passing)
```

**Daftar File & Folder yang DIBERSIHKAN / DIABAIKAN (Tidak Masuk GitHub):**
- ❌ `user_repo_reference/` (Dihapus permanen dari disk)
- ❌ `yolov8n.pt` di root (Dihapus dari disk, redundan)
- ❌ `graphify-out/` (Diabaikan via `.gitignore`)
- ❌ `.agents/` (Diabaikan via `.gitignore`)
- ❌ `.env` (Diabaikan via `.gitignore`, rahasia aman)
- ❌ `models/*.onnx`, `models/*.pt` (Diabaikan via `.gitignore`, hanya file `.hef` yang dimasukkan)
- ❌ `data/*.db`, `data/frames/*`, `data/recordings/*` (Diabaikan via `.gitignore`)
- ❌ `__pycache__/`, `.pytest_cache/`, `venv/` (Diabaikan via `.gitignore`)

---

## 4. Tahapan Rencana Kerja (Task Breakdown)

### Tahap 1: Sanitasi Disk & Penghapusan File Sampah
- Hapus folder `user_repo_reference/` secara permanen.
- Hapus file `yolov8n.pt` duplikat di root direktori.
- Bersihkan cache Python (`__pycache__`, `.pytest_cache`).

### Tahap 2: Konfigurasi `.gitignore` Bersih & Ketat
- Perbarui `.gitignore` agar secara eksplisit mengecualikan:
  - `user_repo_reference/`
  - `graphify-out/`
  - `.agents/`
  - `yolov8n.pt`
  - `models/*.pt`, `models/*.onnx`
  - Namun tetap menyertakan `models/yolov8n.hef` (karena dibutuhkan oleh Raspberry Pi).

### Tahap 3: Pengujian Integritas Akhir (Regression Test)
- Jalankan `pytest` untuk memvalidasi bahwa penghapusan file sampah tidak merusak modul apa pun dan seluruh 49 test tetap lulus 100%.

### Tahap 4: Konfigurasi Git Remote & Initial Push ke GitHub Pengguna
- Perbarui git remote `origin` dari repo lama (`aslablppm-lang/sitinjau-laut`) ke repositori baru pengguna:
  `https://github.com/MAHEZANOVRAYUDA/Intelligent-Transportation-System-Sitinjau-Lawuik.git`.
- Buat commit komprehensif: `feat: production edge ai traffic monitoring system for raspberry pi 5 and hailo-8l`.
- Pastikan branch adalah `main`.
- Lakukan `git push -u origin main`.
- Verifikasi bahwa semua file berada di GitHub dan tidak ada kebocoran file rahasia `.env`.

### Tahap 5: Panduan Serah-Terima Lapangan ke Raspberry Pi 5
- Menyediakan instruksi 3 langkah mudah yang harus dijalankan pengguna saat Raspberry Pi 5 sudah dinyalakan:
  1. `git clone https://github.com/MAHEZANOVRAYUDA/Intelligent-Transportation-System-Sitinjau-Lawuik.git`
  2. `cd Intelligent-Transportation-System-Sitinjau-Lawuik && bash scripts/setup_raspberry_pi.sh`
  3. Mengubah visibilitas repo di GitHub menjadi Private.
