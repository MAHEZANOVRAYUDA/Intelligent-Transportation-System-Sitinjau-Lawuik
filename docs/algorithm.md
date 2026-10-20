# Dokumentasi Algoritma — Sitinjau Laut Traffic Monitoring

Dokumen ini mendokumentasikan rumus-rumus yang digunakan dalam sistem, sebagai dasar klaim penelitian ilmiah.

## 0. Status modifikasi vs YOLO asli (penting untuk paper)

**Detektor YOLOv8 saat ini BELUM dimodifikasi rumusnya.**

| Komponen | Status | Keterangan |
|---|---|---|
| Arsitektur YOLOv8n | **Standar Ultralytics** | `yolov8n.pt` pretrained COCO |
| Loss CIoU / BCE / DFL | **Standar, belum diubah** | Tidak ada custom `loss.py` |
| Bobot model | **Pretrained COCO** | Belum fine-tune dataset Sitinjau Laut |
| Ambang confidence | **Disetel, bukan rumus baru** | `conf=0.15` di `settings.yaml` |
| IoU NMS | **Disetel** | `iou=0.5` |
| Mapping kelas | **Kustom aplikasi** | COCO `car/motorcycle/bus/truck` → `mobil/motor/bus/truck` |
| Tracker | **Kustom penelitian** | Kalman + Mahalanobis + \(\lambda(1-\mathrm{IoU})^2\) (bukan ByteTrack) |
| Counting line | **Kustom** | Cross-product sisi garis |
| Lane divider | **Kustom opsional** | Filter IN/OUT berdasarkan lajur |
| Utilisasi jalan | **Kustom penelitian** | \(U = V_{used}/C_{total}\) meter-lajur |

Untuk eksperimen paper (sebelum vs sesudah):

1. **Baseline (sekarang):** YOLO asli + threshold + tracker/counting kustom.
2. **Perlakuan:** baru kemudian ubah loss / fine-tune / PCU weighting, lalu bandingkan mAP, precision/recall, dan error counting.

Jangan klaim “modifikasi rumus YOLO” sebelum file training/loss kustom ada. Yang sudah original untuk paper hari ini adalah **asosiasi \(D^{**}_{ij}\), counting, occupancy meter-lajur, dan status lancar/padat/macet**.



### 1.1 Pipeline

```
Frame (640×640) → CSPDarknet Backbone → PANet Neck → Decoupled Head → Bounding Boxes
```

### 1.2 Loss Function

Total loss YOLOv8:

\[
\mathcal{L}_{total} = \lambda_{box} \cdot \mathcal{L}_{CIoU} + \lambda_{cls} \cdot \mathcal{L}_{BCE} + \lambda_{dfl} \cdot \mathcal{L}_{DFL}
\]

**Complete IoU Loss:**

\[
\mathcal{L}_{CIoU} = 1 - IoU + \frac{\rho^2(b, b^{gt})}{c^2} + \alpha \cdot v
\]

where:
- \(IoU\) = Intersection over Union
- \(\rho\) = Euclidean distance between box centers
- \(c\) = diagonal length of smallest enclosing box
- \(v\) = consistency of aspect ratio
- \(\alpha = \frac{v}{(1-IoU)+v}\)

### 1.3 Mapping Kelas

| COCO Class | Kelas Lokal | Panjang + Gap (m) |
|---|---|---|
| motorcycle | motor | 2,5 |
| car | mobil | 6,0 |
| bus | bus | 14,0 |
| truck | truck | 12,0 |

## 2. Vehicle Tracking dan Asosiasi Data

Deteksi YOLO **tidak diubah rumusnya**. Pengembangan rumus ada pada **asosiasi track–deteksi**.

Filter Kalman 7D (gaya SORT) menghasilkan prediksi \(y_i\) dan kovarians inovasi \(S_i\).

**Jarak Mahalanobis (DeepSORT):**

\[
D_{ij} = (d_j - y_i)^{T} S_i^{-1}(d_j - y_i)
\]

**Term konsistensi temporal:** \(T_{ij} = \mathrm{IoU}(B_j^{t}, B_i^{t-1})\)

\[
D^{*}_{ij} = D_{ij} + \lambda(1 - T_{ij})
\]

\[
D^{**}_{ij} = D_{ij} + \lambda(1 - T_{ij})^{2}
\]

Default sistem: **\(D^{**}_{ij}\)** (`tracking.association: quadratic`). Alternatif di `settings.yaml`: `mahalanobis` atau `linear`.

Pencocokan per kelas kendaraan, Hungarian assignment, gerbang \(\chi^2\) 4-DOF. Saat YOLO miss-frame, bbox track tetap diprediksi Kalman (ID tidak putus).

## 3. Line Crossing Detection

Garis virtual: \(\overline{P_1(x_1,y_1) \cdot P_2(x_2,y_2)}\)

Cross product untuk menentukan sisi:

\[
side = (x_2 - x_1)(p_y - y_1) - (y_2 - y_1)(p_x - x_1)
\]

- \(side \geq 0\) → above
- \(side < 0\) → below

Crossing terdeteksi saat \(side_{t-1} \neq side_t\) untuk track ID yang sama.

## 4. Perhitungan Kapasitas Jalan

### 4.1 Kapasitas Total

\[
C_{total} = 56.100 \text{ meter-lajur}
\]

Dihitung dari:
- 65% × 16,5 km × 2 lajur = 21.450 m·l
- 35% × 16,5 km × 6 lajur = 34.650 m·l
- Total = 56.100 m·l

### 4.2 Volume Terpakai

\[
V_{used} = \sum_{i \in \{motor, mobil, bus, truck\}} n_i \cdot L_i
\]

where:
- \(n_i\) = jumlah kendaraan tipe \(i\) yang sedang di jalan (antara Gerbang A dan B)
- \(L_i\) = panjang kendaraan + gap

### 4.3 Persentase Utilisasi

\[
U = \frac{V_{used}}{C_{total}} \times 100\%
\]

## 5. Klasifikasi Status Lalu Lintas

| Kondisi | Status |
|---|---|
| \(U \leq 50\%\) | Lancar |
| \(50\% < U \leq 75\%\) | Padat |
| \(U > 75\%\) | Macet |

## 6. Estimasi Kendaraan di Jalan (Single-Gate Mode) & Adaptive Transit Delay

Pada mode Single-Gate (hanya Gerbang A aktif), sistem menerapkan **Adaptive Transit Delay** berbasis fungsi tundaan Bureau of Public Roads (BPR) dan hubungan kecepatan-arus PKJI 2023:

\[
T_{transit}(DS) = \min\left(T_0 \cdot \left[1 + \alpha \cdot (DS_{eff})^\beta\right],\, T_{max}\right)
\]

where:
- \(T_0 = 1.500 \text{ detik}\) (\(\approx 25 \text{ menit}\) @ \(40 \text{ km/jam}\), waktu tempuh arus bebas koridor 16,5 km)
- \(DS_{eff}\) = Derajat kejenuhan efektif (\(\max(DS_{crossing}, Load_{ratio})\))
- \(\alpha = 2,5\) (faktor penalti kelandaian tanjakan ekstrem Sitinjau Lauik \(>8\%\))
- \(\beta = 2,0\) (eksponen akselerasi tundaan kemacetan)
- \(T_{max} = 9.000 \text{ detik}\) (\(2,5 \text{ jam}\), batas Soft TTL keselamatan koridor)

**Kecepatan Operasional Estimasi:**
\[
v_{est} = \frac{16,5 \text{ km}}{T_{transit} / 3600} \text{ [km/jam]}
\]

Mekanisme ini mencegah *false recovery* (antrean kendaraan luruh semu padahal jalan sedang macet total/merayap). Kendaraan dengan \(t_{enter} < t_{now} - T_{transit}(DS)\) dilepaskan secara adaptif.

## 7. Area Modifikasi untuk Penelitian

Rumus-rumus di atas dapat dimodifikasi/dikembangkan:

1. **Passenger Car Unit (PCU) weighting** — motor=0.5, mobil=1.0, bus=2.5, truck=2.5
2. **Weighted utilization** — \(U_w = \frac{\sum n_i \cdot L_i \cdot w_i}{C_{total}} \times 100\%\)
3. **Time-varying capacity** — kapasitas efektif berkurang saat hujan/malam
4. **Directional flow** — analisis A→B vs B→A terpisah
5. **Confidence-weighted counting** — hanya hitung deteksi dengan confidence > threshold adaptif
6. **Custom loss function** — modifikasi \(\mathcal{L}_{CIoU}\) dengan bobot kelas untuk kendaraan Indonesia

## 8. Catatan Ekstrapolasi PKJI 2023 (SE No. 21/SE/Db/2023)

Sistem mengadopsi standar resmi **Surat Edaran Direktur Jenderal Bina Marga No. 21/SE/Db/2023** tentang Pedoman Kapasitas Jalan Indonesia (PKJI 2023) yang diselaraskan dengan Pedoman No. 09/P/BM/2023 untuk segmen jalan antarkota 2/2 TT kelandaian khusus Sitinjau Lauik.

### 8.1 Kapasitas Ruas Praktis

\[
C = C_0 \times FC_w \times FC_{sp} \times FC_{sf}
\]

- \(C_0 = 3.550 \text{ smp/jam}\) (Kapasitas dasar 2 arah kondisi dasar terkoreksi)
- \(W_e = 6,5 \text{ m} \implies FC_w = 0,91\)
- \(FC_{sp} = 1,00\) (Distribusi pemisahan arah seimbang 50:50)
- \(FC_{sf} = 0,91\) (Faktor hambatan samping dan bahu efektif jalan pegunungan)
- **Kapasitas Nyata:** \(C = 3.550 \times 0,91 \times 1,00 \times 0,91 = \mathbf{2.939,76 \text{ smp/jam}}\) (\(\approx 2.940 \text{ smp/jam}\) pada tampilan antarmuka)

### 8.2 Interpolasi Linier Faktor Lebar Jalur (\(FC_w\))

Pada tabel standar PKJI 2023 untuk jalan 2/2 TT segmen khusus:
- \(W_e = 6,0 \text{ m} \to FC_w = 0,82\)
- \(W_e = 7,0 \text{ m} \to FC_w = 1,00\)

Untuk lebar perkerasan efektif Sitinjau Lauik \(W_e = 6,5 \text{ m}\), diterapkan interpolasi linier kontinu:

\[
FC_w(6,5) = FC_w(6,0) + \frac{6,5 - 6,0}{7,0 - 6,0} \times \left(FC_w(7,0) - FC_w(6,0)\right) = 0,82 + 0,5 \times (1,00 - 0,82) = \mathbf{0,91}
\]

### 8.3 Bobot Ekivalen Mobil Penumpang (\(ekr\)) Berbobot Arah

Tanjakan Sitinjau Lauik memiliki kelandaian ekstrem mencapai \(12\% - 16\%\) pada Panorama 2 dengan panjang tanjakan kritis \(> 1 \text{ km}\). Hal ini memicu fenomena *crawl speed* pada kendaraan berat:

| Moda Kendaraan | Simbol | Bobot Menanjak (Naik) | Bobot Menurun (Turun) | Keterangan Akademis |
|---|:---:|:---:|:---:|---|
| Sepeda Motor | \(MC\) | 0,40 | 0,40 | Kelincahan manuver di sela antrean |
| Mobil Penumpang | \(LV\) | 1,00 | 1,00 | Basis referensi kesetaraan mobil |
| Bus Angkutan | \(LB\) | 2,50 | 1,60 | Reduksi manuver pada tikungan tajam Panorama 1 & 2 |
| Truk Barang | \(HV\) | 8,90 | 2,50 | Kelandaian curam \(\ge 8\%\); kecepatan anjlok \(< 20\text{ km/jam}\) |

### 8.4 Penyelarasan Taksonomi: Formulasi Composite Expected EMP (\(E[emp]\))

PKJI 2023 menetapkan 6 kelas kendaraan: **MP** (Mobil Penumpang), **KS** (Kendaraan Sedang), **BB** (Bus Besar), **TB** (Truk Besar), **SM** (Sepeda Motor), dan **KTB** (Kendaraan Tak Bermotor). Sementara itu, sensor visual berbasis deteksi objek kamera (YOLO) mengelompokkan kendaraan dalam 4 kategori makro visual: `Sepeda Motor`, `Mobil Penumpang`, `Bus Angkutan`, dan `Truk Barang`.

Untuk menjembatani resolusi sensor visual dengan ketetapan 6 kelas PKJI 2023 secara saintifik tanpa bias galat, sistem menerapkan formulasi nilai harapan matematis (*conditional expectation*):

\[
E[emp_{\text{bus}}] = P(\text{KS} \mid \text{bus}) \cdot emp_{\text{KS}} + P(\text{BB} \mid \text{bus}) \cdot emp_{\text{BB}}
\]

\[
E[emp_{\text{truk}}] = P(\text{KS} \mid \text{truk}) \cdot emp_{\text{KS}} + P(\text{TB} \mid \text{truk}) \cdot emp_{\text{TB}}
\]

Dengan konstrain probabilitas:
\[
P(\text{KS} \mid \text{moda}) + P(\text{Besar} \mid \text{moda}) = 1,0
\]

#### Nilai Parameter Empiris Sitinjau Lauik:
- **Arah Menanjak (Uphill):**
  - \(emp_{\text{KS}} = 1,50\) (Truk 2-as kecil / Bus mikro)
  - \(emp_{\text{BB}} = 2,50\) (Bus besar antarkota)
  - \(emp_{\text{TB}} = 8,90\) (Truk tronton, CPO, gandeng)
- **Arah Menurun (Downhill):**
  - \(emp_{\text{KS}} = 1,20\)
  - \(emp_{\text{BB}} = 1,60\)
  - \(emp_{\text{TB}} = 2,50\)

Pada baseline keselamatan konservatif puncak, \(P(\text{TB}) = 1,0\) dan \(P(\text{BB}) = 1,0\) sehingga \(E[emp_{\text{truk}}] = 8,90\) dan \(E[emp_{\text{bus}}] = 2,50\). Ketika survei komposisi armada lokal diterapkan (misal \(45\%\) truk sedang dan \(55\%\) tronton), nilai \(E[emp_{\text{truk}}]\) terkalibrasi secara dinamis ke \(5,57\) pada arah menanjak dan \(1,92\) pada arah menurun.

## Referensi

- Surat Edaran Direktur Jenderal Bina Marga No. 21/SE/Db/2023 tentang Pedoman Kapasitas Jalan Indonesia (PKJI 2023).
- Pedoman Ditjen Bina Marga No. 09/P/BM/2023 tentang Kapasitas Jalan Indonesia.
- Redmon, J., et al. (2016). "You Only Look Once: Unified, Real-Time Object Detection".
- Highway Capacity Manual (HCM 2010 / HCM 6th Edition) — Analysis of Specific Grades & Climbing Lanes.
- BPR Volume-Delay Function: \(t = t_0[1 + \alpha(V/C)^\beta]\).
