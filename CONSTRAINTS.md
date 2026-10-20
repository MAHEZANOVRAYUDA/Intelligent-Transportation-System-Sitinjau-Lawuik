# Project Quality Constraints & Guardrails
# Sitinjau Laut Traffic Monitoring System (Dishub Sumbar & LPPM UPI YPTK)

Dokumen ini mendefinisikan batasan kualitas, ambang performa, dan standar arsitektur non-negotiable untuk sistem pemantauan lalu lintas Sitinjau Lauik. Setiap kontribusi atau perubahan kode wajib mematuhi kontrak kualitas di bawah ini.

---

## 1. Quality & Testing Floor (Non-Negotiable)

| Dimensi | Ambang Batas (Floor) | Enforcement / Tool | Justifikasi Teknis |
| :--- | :--- | :--- | :--- |
| **Test Suite Pass Rate** | **100% (0 failure)** | `pytest` | Seluruh 49 unit & integration test wajib lulus sebelum merge/deploy. |
| **Schema Validation** | **Pydantic v2 (Strict)** | `pydantic>=2.5.0` | Semua payload config (`settings.yaml`) dan endpoint API (`/api/dev/*`) wajib tervalidasi skema runtime tanpa tipe `Any`. |
| **Formula Integrity** | **PKJI 2023 & SE No. 21/2023** | `tests/test_pkji_api.py`, `tests/test_occupancy.py` | Rumus kapasitas praktis $C = C_0 \times FC_w \times FC_{sp} \times FC_{sf}$ dan $DS = Q/C$ tidak boleh diubah tanpa justifikasi regulasi Bina Marga. |
| **Tracking Stability** | **Quadratic Consistency $D^{**}_{ij}$** | `tests/test_association.py` | Asosiasi Kalman wajib mempertahankan ID objek pada frame skip dan deviasi IoU tinggi. |

---

## 2. AI Inference & Computer Vision Budgets

| Metrik | Budget Target | Fallback / Guardrail |
| :--- | :--- | :--- |
| **YOLO Inference Latency (CPU)** | $\le 75$ ms / frame | Frame skip aktif (`detect_every_n: 2`) untuk menjaga throughput $\ge 15$ FPS. |
| **YOLO Inference Latency (GPU)** | $\le 20$ ms / frame | NVIDIA TensorRT / CUDA runtime. |
| **Input Resolution** | Max $960\times960$ | Mencegah OOM pada edge device dan menjaga deteksi motor jarak jauh. |
| **Confidence Gate** | Min $0.15$ (raw), $0.28$ (motor), $0.18$ (mobil) | Mencegah ghost detection dari partikel kabut/hujan Sitinjau Lauik. |
| **Kalman Filter Conditioning** | Matriks $R$ adaptif terhadap luas box $s$ | Mencegah matrix singular / ill-conditioned inversion pada truk tronton Full HD. |

---

## 3. Memory Safety & Corridor State Guardrails

- **Rolling Window Purge:** Seluruh event perlintasan (`CrossingEvent`) lebih tua dari 1 jam **wajib** dipurging dari RAM setiap siklus snapshot.
- **Dual Gate Soft TTL:** Kendaraan dalam koridor dibatasi maksimum 9.000 detik (2,5 jam). Kendaraan yang tidak terdeteksi keluar setelah batas ini otomatis dilepaskan untuk mencegah *cumulative integrator drift* (kendaraan hantu).
- **Zero Memory Leaks on Video Stream:** Buffer frame OpenCV RTSP diatur `buffer_size: 1` (`cv2.CAP_PROP_BUFFERSIZE = 1`) untuk mencegah lag akumulatif pada feed RTSP.

---

## 4. Web Performance & Core Web Vitals Budgets

| Metrik Webperf | Budget Target | Status Audit Saat Ini | Tindakan Perbaikan |
| :--- | :--- | :--- | :--- |
| **HTML Initial Payload** | $\le 50$ KB | ⚠️ **171.5 KB** (6.321 baris) | Ekstraksi ~3.200 baris GeoJSON koordinat ke file static JSON terpisah. |
| **LCP (Largest Contentful Paint)**| $\le 2.0$ detik | ⚠️ Tergantung CDN pihak ketiga | Self-host vendor CSS/JS (MapLibre & Fonts) untuk ketahanan offline di tanjakan. |
| **INP (Interaction to Next Paint)**| $\le 100$ ms | ✅ Terpenuhi | Hindari `chart.update()` penuh; gunakan update canvas inkremental. |
| **CLS (Cumulative Layout Shift)** | $\le 0.05$ | ✅ Terpenuhi | Container peta dan panel metrik memiliki dimensi eksplisit. |

---

## 5. Database & Async Concurrency Guardrails

- **Zero Blocking Queries on Event Loop:** Fungsi `get_today_crossings()` dan operasi database SQLite **dilarang** memblokir event loop async FastAPI. Operasi agregasi berat wajib dieksekusi via threadpool `run_in_executor` atau dicache secara in-memory dalam worker.
- **Connection Leak Prevention:** Setiap session SQLAlchemy wajib ditutup dalam blok `finally: session.close()`.
