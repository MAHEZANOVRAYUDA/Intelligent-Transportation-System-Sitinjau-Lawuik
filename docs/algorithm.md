# Dokumentasi Algoritma — Sitinjau Laut Traffic Monitoring

Dokumen ini mendokumentasikan rumus-rumus yang digunakan dalam sistem, sebagai dasar klaim penelitian ilmiah.

## 0. Status modifikasi vs YOLO asli (penting untuk paper)

**Detektor YOLOv8 saat ini BELUM dimodifikasi rumusnya.**

| Komponen | Status | Keterangan |
|---|---|---|
| Arsitektur YOLOv8n | **Standar Ultralytics** | `yolov8n.pt` pretrained COCO |
| Loss CIoU / BCE / DFL | **Standar, belum diubah** | Tidak ada custom `loss.py` |
| Bobot model | **Pretrained COCO** | Belum fine-tune dataset Sitinjau Laut |
| Ambang confidence | **Disetel, bukan rumus baru** | `conf=0.35` di `settings.yaml` |
| IoU NMS | **Disetel** | `iou=0.5` |
| Mapping kelas | **Kustom aplikasi** | COCO `car/motorcycle/bus/truck` → `mobil/motor/bus/truck` |
| Tracker | **Kustom (bukan ByteTrack default)** | Centroid + matching per kelas + voting |
| Counting line | **Kustom** | Cross-product sisi garis |
| Lane divider | **Kustom opsional** | Filter IN/OUT berdasarkan lajur |
| Utilisasi jalan | **Kustom penelitian** | \(U = V_{used}/C_{total}\) meter-lajur |

Untuk eksperimen paper (sebelum vs sesudah):

1. **Baseline (sekarang):** YOLO asli + threshold + tracker/counting kustom.
2. **Perlakuan:** baru kemudian ubah loss / fine-tune / PCU weighting, lalu bandingkan mAP, precision/recall, dan error counting.

Jangan klaim “modifikasi rumus YOLO” sebelum file training/loss kustom ada. Yang sudah original untuk paper hari ini adalah **counting, occupancy meter-lajur, dan status lancar/padat/macet**.



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

## 2. Vehicle Tracking

Centroid-based tracking dengan Hungarian assignment:

\[
d(t_i, d_j) = \sqrt{(cx_i - cx_j)^2 + (cy_i - cy_j)^2}
\]

Match jika \(d < d_{max}\) (default 80 pixel) dan class sama.

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

## 6. Estimasi Kendaraan di Jalan (Single-Gate Mode)

Saat hanya Gerbang A aktif, kendaraan dihapus dari estimasi setelah waktu tempuh:

\[
T_{transit} = \frac{D}{v_{avg}} = \frac{16.500 \text{ m}}{40 \text{ km/jam}} \approx 1.485 \text{ detik}
\]

Kendaraan dengan \(t_{enter} < t_{now} - T_{transit}\) dianggap sudah keluar.

## 7. Area Modifikasi untuk Penelitian

Rumus-rumus di atas dapat dimodifikasi/dikembangkan:

1. **Passenger Car Unit (PCU) weighting** — motor=0.5, mobil=1.0, bus=2.5, truck=2.5
2. **Weighted utilization** — \(U_w = \frac{\sum n_i \cdot L_i \cdot w_i}{C_{total}} \times 100\%\)
3. **Time-varying capacity** — kapasitas efektif berkurang saat hujan/malam
4. **Directional flow** — analisis A→B vs B→A terpisah
5. **Confidence-weighted counting** — hanya hitung deteksi dengan confidence > threshold adaptif
6. **Custom loss function** — modifikasi \(\mathcal{L}_{CIoU}\) dengan bobot kelas untuk kendaraan Indonesia

## Referensi

- Redmon, J., et al. (2016). "You Only Look Once: Unified, Real-Time Object Detection"
- Ultralytics YOLOv8 Documentation: https://docs.ultralytics.com
- Highway Capacity Manual (HCM 2010) — Level of Service methodology
- BPR Volume-Delay Function: \(t = t_0[1 + \alpha(V/C)^\beta]\)
