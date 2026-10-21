#!/usr/bin/env bash
# ==============================================================================
# Script Instalasi & Konfigurasi Systemd Service untuk Sitinjau Edge (Raspberry Pi 5)
# Menangani deteksi otomatis user, direktori, python venv, serta permission Hailo-8L
# ==============================================================================

set -e

GATE="${1:-B}"
CURRENT_USER="$(whoami)"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PYTHON="${REPO_DIR}/venv/bin/python3"

echo "=========================================================="
echo "   SITINJAU LAUIK - INSTALASI EDGE SERVICE (GERBANG ${GATE})"
echo "=========================================================="
echo "User         : ${CURRENT_USER}"
echo "Direktori    : ${REPO_DIR}"
echo "Python Exec  : ${VENV_PYTHON}"
echo "Gerbang      : ${GATE}"
echo "----------------------------------------------------------"

if [ ! -f "${VENV_PYTHON}" ]; then
    echo "[!] Virtual environment tidak ditemukan di ${VENV_PYTHON}."
    echo "[*] Menggunakan python3 sistem: $(which python3)"
    VENV_PYTHON="$(which python3)"
fi

# 1. Pastikan izin akses fisik chip Hailo-8L
if [ -e "/dev/hailo0" ]; then
    echo "[+] Menyetel permission /dev/hailo0 agar dapat diakses user..."
    sudo chmod 666 /dev/hailo0 || true
fi

# 2. Generate file systemd service
SERVICE_FILE="/etc/systemd/system/sitinjau-edge.service"

echo "[+] Menulis konfigurasi service ke ${SERVICE_FILE}..."

sudo bash -c "cat <<EOF > ${SERVICE_FILE}
[Unit]
Description=Layanan Edge AI Sitinjau Lauik Gerbang ${GATE} (Hailo-8L)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${CURRENT_USER}
WorkingDirectory=${REPO_DIR}
EnvironmentFile=-${REPO_DIR}/.env
ExecStart=${VENV_PYTHON} main_edge.py --gate ${GATE} --backend auto --interval 5 --web-stream
Restart=always
RestartSec=10
KillMode=process
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF"

# 3. Reload daemon & enable service
echo "[+] Reloading systemd daemon..."
sudo systemctl daemon-reload

echo "[+] Mengaktifkan service sitinjau-edge agar jalan otomatis saat boot..."
sudo systemctl enable sitinjau-edge

echo ""
echo "=========================================================="
echo " Instalasi Service Berhasil!"
echo " Perintah untuk mengelola layanan di Raspberry Pi:"
echo "   - Menjalankan   : sudo systemctl start sitinjau-edge"
echo "   - Cek status    : sudo systemctl status sitinjau-edge"
echo "   - Menghentikan  : sudo systemctl stop sitinjau-edge"
echo "   - Cek log live  : journalctl -u sitinjau-edge -f"
echo "   - Web preview   : Buka http://<ip-raspberry>:8080 di browser"
echo "=========================================================="
