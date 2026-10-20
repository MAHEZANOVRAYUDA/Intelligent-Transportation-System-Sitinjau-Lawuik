# Dokumentasi Proyek — Monitoring Lalu Lintas Jalan Sitinjau Laut

**Versi dokumen:** 1.0  
**Tanggal:** 24 Agustus 2026  
**Status sistem:** prototipe perangkat lunak (Fase 1), kamera lapangan Gerbang B dan Raspberry Pi 5 + Coral belum diintegrasikan  
**Calon pengadopsi:** Dinas Perhubungan Provinsi Sumatera Barat

Dokumen ini merangkum proyek dari awal: tujuan, arsitektur, apa yang sudah selesai, apa yang belum, dan arah pengembangan berikutnya. Gunakan bersama `README.md` (cara menjalankan) dan `docs/algorithm.md` (rumus untuk paper).

---

## 1. Latar belakang dan tujuan

Sistem ini memantau volume kendaraan di Jalan Sitinjau Laut menggunakan kamera dan deteksi objek. Objek dibagi dua gerbang:

| Gerbang | Lokasi konsep | Peran |
|---|---|---|
| **A** | dekat Kota Padang | hitung kendaraan yang masuk/keluar koridor |
| **B** | dekat perbatasan Sitinjau Laut–Kabupaten Solok | pasangan dual-gate (belum dipasang) |

**Tujuan utama**

1. Mendeteksi setiap kendaraan yang lewat.
2. Mengklasifikasikan jenis: **motor, mobil, bus, truck**.
3. Menyimpan event ke database.
4. Menghitung persentase kapasitas terpakai pada rentang A–B (meter-lajur).
5. Menampilkan status: **lancar** (≤50%), **padat** (50–75%), **macet** (>75%).

**Keluaran yang direncanakan**

- Halaman web: monitoring + status lalu lintas + live cam **tanpa** kotak deteksi.
- Aplikasi mobile: hanya informasi hasil monitoring (API sudah disiapkan; aplikasi belum dibuat).
- Dev Mode: overlay bounding box + kalibrasi garis (hanya untuk pengembangan).

Anggaran terbatas. Prioritas: Raspberry Pi 5 + Google Coral USB per gerbang, kamera IP outdoor, SSD (bukan SD card untuk data), pendingin, UPS.

---

## 2. Spesifikasi jalan (data operasional)

| Parameter | Nilai |
|---|---|
| Panjang A → B | 16,5 km |
| 65% ruas | muat 2 kendaraan sejajar |
| 35% ruas | muat 6 kendaraan sejajar |
| Kapasitas total | **56.100 meter-lajur** |

Panjang kendaraan sudah termasuk gap:

| Jenis | Panjang (m) | Kelas COCO |
|---|---|---|
| Motor | 2,5 | motorcycle |
| Mobil | 6,0 | car |
| Bus | 14,0 | bus |
| Truck | 12,0 | truck |

Rumus utilisasi:

\[
V_{used} = \sum n_i \cdot L_i,\quad U = \frac{V_{used}}{56.100} \times 100\%
\]

Mode saat ini **single-gate**: hanya Gerbang A. Kendaraan yang tercatat IN dianggap masih di koridor hingga waktu tempuh estimasi (~25 menit pada 40 km/jam) atau tercatat OUT di kamera yang sama.

---

## 3. Arsitektur teknis

```
Kamera IP (RTSP)
        │
        ▼
 StreamManager  (satu koneksi, buffer=1)
        ├── DetectionWorker  → YOLO → Tracker → LineCounter → SQLite
        │                         └── Occupancy (meter-lajur, status)
        └── MJPEG bersih     → Dashboard produksi (/)
              MJPEG overlay  → Dev Mode (/dev)
```

| Lapisan | Teknologi |
|---|---|
| Deteksi | YOLOv8n Ultralytics, pretrained COCO |
| Tracking | Kalman SORT + asosiasi \(D^{**}_{ij}\) + voting kelas |
| Counting | garis virtual + (opsional) pemisah lajur |
| Backend | FastAPI + Uvicorn |
| Data | SQLite (`data/sitinjau_laut.db`) |
| Dashboard | HTML/CSS/JS statis |
| Target produksi | Raspberry Pi 5 8GB + Coral USB + SSD |

**Penting untuk paper:** rumus internal YOLO (CIoU, BCE, DFL) **belum diubah**. Lihat `docs/algorithm.md` bagian 0.

---

## 4. Struktur repositori

```
Sitinjau Laut/
├── run.py                    # entry point server
├── requirements.txt
├── .env                      # rahasia RTSP (jangan commit)
├── .env.example
├── config/settings.yaml      # jalan, gerbang, model, garis kalibrasi
├── models/yolov8n.pt         # bobot (diunduh otomatis jika belum ada)
├── src/
│   ├── config.py
│   ├── capture/stream_manager.py
│   ├── detection/            # detector, tracker, visualizer
│   ├── counting/line_counter.py
│   ├── analytics/density.py
│   ├── storage/database.py
│   ├── worker/detection_worker.py
│   └── api/                  # main.py, routes/dev.py, state.py
├── static/dashboard/         # produksi
├── static/dev/               # pengembangan + kalibrasi
├── data/                     # db, frame uji
└── docs/
    ├── PROJECT.md            # dokumen ini
    └── algorithm.md          # rumus ilmiah
```

---

## 5. Tahap pengerjaan — sudah sampai mana

Proyek dimulai dari workspace kosong. Pengembangan **software-first**: kamera Bardi IP (RTSP) dipakai sebagai prototipe sebelum hardware lapangan lengkap.

### Selesai

| Item | Keterangan |
|---|---|
| Pipeline RTSP | satu reader, auto-reconnect, buffer minim |
| YOLOv8n | deteksi 4 kelas kendaraan |
| Tracker | Kalman + \(D^{**}_{ij}\), ID bertahan saat miss-frame, voting kelas |
| Counting line | garis merah, arah IN up/down |
| Lane divider | garis cyan, sisi IN kiri/kanan |
| Kalibrasi Dev Mode | klik/geser garis, **Simpan config** ke `settings.yaml` |
| Occupancy | meter-lajur + lancar/padat/macet |
| SQLite | event crossing + snapshot |
| Dashboard `/` | status, live cam tanpa kotak, angka live + koridor |
| Dev Mode `/dev` | bounding box, FPS, IN/OUT, track |
| API + WebSocket | siap mobile |
| Performa | inferensi tiap 3 frame; overlay max 1280px; reload Uvicorn dimatikan |

### Kamera prototipe

URL RTSP Gerbang A ada di `.env` (`GATE_A_RTSP_URL`). Gerbang B masih kosong.

### Belum selesai / belum ada

| Item | Catatan |
|---|---|
| Gerbang B fisik | kamera + Pi + Coral belum |
| Dual-gate occupancy | kode mendukung jika `GATE_B_RTSP_URL` diisi |
| Fine-tune YOLO | dataset kendaraan Indonesia belum dilatih |
| Modifikasi loss YOLO | belum; baseline Ultralytics |
| Aplikasi mobile | API ada, UI belum |
| Laporan Dishub otomatis | belum |
| Deploy Raspberry Pi 5 + Coral | belum |
| UPS, SSD, box pendingin | pengadaan hardware |
| Kalibrasi lapangan final | sudut kamera produksi berbeda dari prototipe |
| Uji akurasi terukur | mAP / confusion matrix / error counting belum formal |

**Tahap saat ini secara ringkas:** prototipe desktop yang sudah mendeteksi, menghitung, menampilkan dashboard, dan mengizinkan kalibrasi garis. Belum sistem produksi 24 jam di dua gerbang.

---

## 6. Keputusan desain yang perlu diingat

1. **Live cam produksi tanpa bounding box** — overlay hanya di `/dev`.
2. **Counting line** = kapan kendaraan dihitung (melewati garis).
3. **Lane divider** = lajur mana yang IN vs OUT (penting jika dua arah terlihat).
4. **Angka besar di dashboard (Kendaraan per Jenis)** = kendaraan yang **sedang di ruas A→B** (`on_road`: masuk +1, keluar −1). Subteks = akumulasi tersimpan hari ini. Kartu “Kendaraan di Jalan” = total koridor. Tombol **Hapus data** mengosongkan SQLite + hitungan runtime.
5. Port **8000**. Jika `WinError 10048`, masih ada proses lama: hentikan dulu (lihat README).
6. `API_DEBUG`/reload Uvicorn **dimatikan** di `run.py` karena sempat membuat halaman pending.

---

## 7. Rencana ke depan

### Fase 2 — akurasi dan penelitian

- Kumpulkan frame dari kamera lapangan (siang, malam, hujan).
- Label (Roboflow/CVAT), fine-tune YOLOv8n.
- Catat metrik **sebelum vs sesudah** fine-tune (jangan klaim rumus YOLO berubah jika hanya fine-tune bobot).
- Jika paper membutuhkan rumus baru: ubah loss / PCU / utilisasi di kode terpisah, bandingkan dengan baseline commit ini.
- Rapikan kalibrasi garis di lokasi final.

### Fase 3 — dual gate dan occupancy benar

- Pasang kamera Gerbang B, isi `GATE_B_RTSP_URL`.
- IN di A dan OUT di B (dan sebaliknya) untuk isi koridor, bukan hanya timeout 25 menit.
- Satu set Pi 5 + Coral per gerbang (disarankan, bukan satu Pi untuk dua kamera).

### Fase 4 — produksi Dishub

- Deploy SSD + pendingin + UPS + watchdog (restart layanan).
- Export TFLite/Edge TPU untuk Coral.
- Dashboard laporan harian/jam-an.
- Aplikasi mobile hanya konsumsi `/api/monitoring/current` dan `/ws/monitoring`.
- Serah terima: SOP, cadangan config, retensi data 90 hari.

### Hardware (prioritas anggaran, perkiraan)

Daftar lengkap pengadaan, ESP32+LCD+fan, dan analisis kompatibilitas: `docs/hardware_integrasi.md` (canvas ringkasan di sesi Cursor).

- 2× Raspberry Pi 5 8GB + Hailo-8L (Coral USB hanya cadangan)
- 2× SSD 256GB USB3, 2× UPS, 2× kamera IP outdoor PoE
- 2× ESP32 + LCD 20×4 monokrom + MOSFET fan 12 V
- 2× router 4G industri + kabinet IP65  

---

## 8. Cara menjalankan dan menghentikan

Lihat juga `README.md`. Ringkas:

**Jalankan**

```powershell
cd "D:\Sitinjau Laut"
venv\Scripts\activate
python run.py
```

Buka http://127.0.0.1:8000 dan http://127.0.0.1:8000/dev

**Hentikan**

Di terminal yang menjalankan `run.py`: **Ctrl+C**.

Jika port 8000 masih terpakai:

```powershell
netstat -ano | findstr ":8000"
taskkill /PID <nomor_PID> /F
```

---

## 9. Konfigurasi penting

| File | Isi |
|---|---|
| `.env` | URL RTSP, port API, device deteksi |
| `config/settings.yaml` | kapasitas jalan, threshold, garis counting/lajur, confidence YOLO |

Setelah kalibrasi di Dev Mode, tekan **Simpan config** agar garis tidak hilang saat restart.

---

## 10. Catatan sesi pengembangan (hingga 24 Agu 2026)

- Workspace awal kosong; Fase 1 software dibangun di PC Windows dengan kamera Bardi RTSP.
- Deteksi sempat tampak “tidak jalan” di dashboard karena produksi tidak menampilkan kotak; Dev Mode ditambahkan.
- Counting sempat overcount; tracker per kelas + umur track minimum ditambahkan.
- Halaman pending: YOLO tiap frame + reload Uvicorn; sudah diturunkan beban dan reload dimatikan.
- Port 8000 sering tertinggal proses lama; selalu hentikan sebelum `python run.py` ulang.
- Panel dashboard “Kendaraan per Jenis” awalnya memakai `live_class_counts` (bbox di kamera), bukan event SQLite. Sudah diubah ke `today_crossings` (tersimpan, per kelas, IN/OUT).
- Counting bisa melewatkan kendaraan yang bbox-nya sudah tampil: `min_count_confidence` (0.40) lebih ketat dari YOLO (0.35); `min_track_age` membuang crossing jika `continue` sebelum `_prev_side` tercatat. Perbaikan: pending crossing, peak confidence, ambang counting 0.30, umur 3, titik acuan tengah-bawah bbox.
- Panel per jenis diubah ke `on_road` realtime (IN +1 / OUT −1). Tombol **Hapus data** → `POST /api/monitoring/reset` mengosongkan SQLite dan hitungan runtime.
- Motor sering tidak tampil karena YOLOv8n COCO menandai pengendara sebagai `person`/`bicycle` lalu filter kelas membuangnya. Perbaikan: bicycle→motor, person di badan jalan→motor (bukan penumpang mobil), `conf=0.15`, `imgsz=960`.
- Asosiasi tracking sesuai dokumen *Pengembangan Rumus Asosiasi Data*: Kalman + \(D^{**}_{ij}=D_{ij}+\lambda(1-T_{ij})^2\). YOLO loss tidak diubah. Prediksi bbox saat miss-frame menstabilkan ID/counting.
- Counting tidak lagi menahan simpan karena confidence/umur tinggi. Overlay yang benar harus masuk DB: `min_count_confidence=0.05`, `min_track_age=1`, Kalman tiap frame, YOLO tiap 2 frame, filter lajur default non-ketat. Klasifikasi bus/truck kecil dikoreksi ke mobil; overlap kotak dideduplikasi. Fine-tune dataset belakangan.
- Partikel overlay (bukan di stream mentah): Kalman/YOLO speck yang dilabel motor. Filter ukuran+confidence motor, overlay hanya bbox terukur, arah IN/OUT dari pusat bbox + sisi lajur (bukan tepi bawah / dy yang bertentangan).

Dokumen ini sengaja ditulis agar pekerjaan bisa dilanjutkan di percakapan/sesi baru tanpa kehilangan konteks.