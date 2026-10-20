# Todo Checklist: Pembersihan, Sanitasi & Push ke GitHub Pengguna

## Phase 1: Sanitasi Workspace & Eliminasi File Sampah
- [ ] Task 1.1: Hapus folder `user_repo_reference/` secara permanen dari disk laptop.
- [ ] Task 1.2: Hapus file duplikat `yolov8n.pt` di root direktori.
- [ ] Task 1.3: Bersihkan direktori cache temporer (`__pycache__`, `.pytest_cache`).

## Phase 2: Penguncian `.gitignore` & Sanitasi Data
- [ ] Task 2.1: Perbarui `.gitignore` agar memblokir `user_repo_reference/`, `graphify-out/`, `.agents/`, `*.pt`, `*.onnx`, dan file runtime data.
- [ ] Task 2.2: Pastikan model biner `models/yolov8n.hef` (12.5MB) diizinkan (whitelisted) agar langsung terikut ke Raspberry Pi.
- [ ] Task 2.3: Pastikan `.env` terproteksi 100% dan hanya `.env.example` yang masuk git.

## Phase 3: Validasi Integritas Sistem (Regression Test)
- [ ] Task 3.1: Jalankan `pytest` untuk memverifikasi 49 unit test tetap lulus 100% setelah pembersihan.

## Phase 4: Konfigurasi Git Remote & Push ke GitHub Pengguna
- [ ] Task 4.1: Alihkan remote origin ke `https://github.com/MAHEZANOVRAYUDA/Intelligent-Transportation-System-Sitinjau-Lawuik.git`.
- [ ] Task 4.2: Stage seluruh file bersih (`git add .`) dan verifikasi daftar staging (`git status`).
- [ ] Task 4.3: Buat commit: `feat: production edge ai traffic monitoring system for raspberry pi 5 and hailo-8l`.
- [ ] Task 4.4: Lakukan `git push -u origin main`.
- [ ] Task 4.5: Verifikasi repositori di GitHub via `gh repo view`.

## Phase 5: Panduan Siap-Jalan Lapangan Raspberry Pi 5
- [ ] Task 5.1: Dokumentasikan instruksi 1-perintah eksekusi untuk Raspberry Pi 5.
- [ ] Task 5.2: Berikan opsi perintah untuk mengubah repo menjadi Private via GitHub CLI setelah di-clone.
