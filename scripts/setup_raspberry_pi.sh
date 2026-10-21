#!/usr/bin/env bash
# ==============================================================================
# Script Instalasi & Konfigurasi Otomatis Node Edge Sitinjau Lauik
# Perangkat Target : Raspberry Pi 5 (2GB RAM) + Hailo-8L M.2 HAT+ (13 TOPS)
# OS               : Raspberry Pi OS Lite (64-bit Headless)
# ==============================================================================

set -e

echo "=============================================================="
echo "  MEMULAI KONFIGURASI OTOMATIS RASPBERRY PI 5 + HAILO-8L      "
echo "=============================================================="

# 1. Konfigurasi Waktu & Timezone
echo "[1/7] Menyesuaikan Zona Waktu ke Asia/Jakarta & NTP..."
sudo timedatectl set-timezone Asia/Jakarta
sudo timedatectl set-ntp true

# 2. Optimalisasi Memori Swap (2GB) untuk Mencegah OOM
echo "[2/7] Memperbesar Swap Memori menjadi 2048 MB..."
if command -v dphys-swapfile &> /dev/null; then
    sudo dphys-swapfile swapoff || true
    sudo sed -i 's/CONF_SWAPSIZE=.*/CONF_SWAPSIZE=2048/' /etc/dphys-swapfile 2>/dev/null || true
    sudo dphys-swapfile setup || true
    sudo dphys-swapfile swapon || true
else
    echo "Menggunakan konfigurasi swapfile Linux standar..."
    sudo swapoff /swapfile 2>/dev/null || true
    if [ ! -f /swapfile ] || [ "$(stat -c%s /swapfile 2>/dev/null || echo 0)" -lt 2000000000 ]; then
        sudo fallocate -l 2G /swapfile 2>/dev/null || sudo dd if=/dev/zero of=/swapfile bs=1M count=2048 status=progress
        sudo chmod 600 /swapfile
        sudo mkswap /swapfile
    fi
    sudo swapon /swapfile 2>/dev/null || true
    if ! grep -q "/swapfile" /etc/fstab; then
        echo "/swapfile none swap sw 0 0" | sudo tee -a /etc/fstab
    fi
fi


# 3. Aktifkan PCIe Gen 3 untuk Throughput Maksimal Hailo NPU
echo "[3/7] Mengonfigurasi PCIe Gen 3 di /boot/firmware/config.txt..."
CONFIG_FILE="/boot/firmware/config.txt"
if [ ! -f "$CONFIG_FILE" ]; then
    CONFIG_FILE="/boot/config.txt"
fi

if ! grep -q "dtparam=pciex1" "$CONFIG_FILE"; then
    echo "dtparam=pciex1" | sudo tee -a "$CONFIG_FILE"
fi
if ! grep -q "dtparam=pciex1_gen=3" "$CONFIG_FILE"; then
    echo "dtparam=pciex1_gen=3" | sudo tee -a "$CONFIG_FILE"
fi

# 4. Update Repositori & Instal Driver Hailo-8L
echo "[4/7] Menginstal driver Hailo-8L dan dependensi sistem..."
sudo apt update
sudo apt install -y hailo-all python3-venv python3-pip git curl libgl1 libglib2.0-0

# 5. Konfigurasi Python Virtual Environment (dengan Akses Paket Sistem Hailo)
echo "[5/7] Menyiapkan Python Virtual Environment..."
PROJ_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJ_DIR"

if [ ! -d "venv" ]; then
    python3 -m venv --system-site-packages venv
fi

source venv/bin/activate
pip install --upgrade pip
pip install -r requirements-edge.txt

# 6. Verifikasi Hardware NPU Hailo
echo "[6/7] Memeriksa deteksi chip Hailo-8L NPU..."
if command -v hailortcli &> /dev/null; then
    hailortcli fw-control identify || echo "Peringatan: Chip Hailo belum terdeteksi. Silakan reboot perangkat."
else
    echo "Peringatan: hailortcli belum tersedia di PATH."
fi

# 7. Registrasi Systemd Service
echo "[7/7] Memasang layanan otomatis sitinjau-edge.service..."
SERVICE_FILE="/etc/systemd/system/sitinjau-edge.service"
sudo cp deployment/sitinjau-edge.service "$SERVICE_FILE"
sudo sed -i "s|/home/adminpi/sitinjau-laut|$PROJ_DIR|g" "$SERVICE_FILE"
sudo sed -i "s|User=adminpi|User=$(whoami)|g" "$SERVICE_FILE"

sudo systemctl daemon-reload
sudo systemctl enable sitinjau-edge.service

echo "=============================================================="
echo "  KONFIGURASI SELESAI DENGAN SUKSES!                          "
echo "  Disarankan untuk melakukan reboot: sudo reboot              "
echo "=============================================================="
