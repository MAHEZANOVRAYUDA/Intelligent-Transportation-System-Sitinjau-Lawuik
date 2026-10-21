# Todo Checklist: Sinkronisasi Dev Gerbang A & B, Kalibrasi Full-Span Bardi, Eliminasi Double Lines, & Edge Hardening

## Phase 1: Full-Span Calibration Coordinates & API State Parity
- [x] Task 1.1: Perbarui koordinat default Gerbang B di `config/settings.yaml` agar membentang penuh 100% resolusi kamera Bardi (`counting_line: [0, 854, 2559, 854]`, `lane_divider: [1150, 0, 1150, 1439]`, `inbound_side: left`).
- [x] Task 1.2: Perbarui endpoint `GET /api/dev/state/{gate_id}` di `src/api/routes/dev.py` agar mengembalikan `frame_width: 2560`, `frame_height: 1440`, serta konfigurasi `lane_divider` yang valid untuk Gerbang B.

## Phase 2: Eliminasi Double Lines pada Visualizer & Stream
- [x] Task 2.1: Modifikasi `annotate_frame` di `src/detection/visualizer.py` dengan parameter `draw_lines: bool = True`. Ketika `draw_lines=False`, jangan cetak garis merah/cyan dan teks kaku ke dalam piksel JPEG video.
- [x] Task 2.2: Setel `draw_lines=False` pada pemanggilan `annotate_frame` di `src/worker/detection_worker.py` dan `main_edge.py` untuk stream dev, sehingga hanya garis interaktif canvas beresolusi tajam yang tampil (standar Gambar 3).

## Phase 3: Frontend UI/UX, Gate Isolation, & Transisi Bersih Tanpa Frame Tertimpa
- [x] Task 3.1: Perbaiki fungsi `switchGate(gateId)` di `static/dev/index.html` agar seketika membersihkan canvas (`ctx.clearRect`), menyembunyikan frame lama (`img.style.opacity = '0'`), dan menampilkan kartu loading/offline berstandar UI elegan (`#video-offline`).
- [x] Task 3.2: Pasang handler event `img.onload` dan `img.onerror` agar frame video baru hanya ditampilkan setelah frame pertama dari stream yang baru berhasil tiba, mencegah gambar kamera sebelumnya membeku dan tertimpa.
- [x] Task 3.3: Perbaiki `updateUI(data)` di `static/dev/index.html` agar tidak ada state leakage (jika `lane_divider` null, setel `draftLane = null` secara eksplisit, bukan mempertahankan garis dari gerbang sebelumnya).
- [x] Task 3.4: Pastikan rendering garis canvas overlay pada Gerbang A dan B membentang rapi penuh (full-span 2-arah) persis seperti Gambar 3.

## Phase 4: Edge Hardening & Dependensi Bebas Error pada Raspberry Pi 5 + Hailo
- [x] Task 4.1: Tambahkan `scipy>=1.11.0` ke `requirements-edge.txt` untuk mendukung algoritma asosiasi Hungarian pada tracker tanpa `ModuleNotFoundError`.
- [x] Task 4.2: Pastikan `deployment/sitinjau-edge.service` menyertakan flag `--web-stream` pada `ExecStart`.
- [x] Task 4.3: Periksa `main_edge.py` agar otomatis menyalakan web streaming port 8080 dan merilis file descriptor PCIe Hailo secara bersih saat dihentikan.

## Phase 5: Verification & End-to-End Testing
- [x] Task 5.1: Jalankan seluruh test suite otomatis (`pytest -v`) dan pastikan 100% test berstatus PASSED.
- [x] Task 5.2: Lakukan git commit & push ke `origin main`.
- [x] Task 5.3: Siapkan instruksi langkah demi langkah yang aman dan jelas untuk eksekusi terminal di Raspberry Pi besok.
