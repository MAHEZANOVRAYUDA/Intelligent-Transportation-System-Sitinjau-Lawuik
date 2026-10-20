#!/usr/bin/env bash
# ==============================================================================
# Script Pembaruan Otomatis Node Edge Sitinjau Lauik (Raspberry Pi 5)
# Menarik pembaruan dari GitHub repo dan me-restart layanan jika ada commit baru
# ==============================================================================

set -e

PROJ_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJ_DIR"

# Ambil status terbaru dari remote repository
git fetch origin main > /dev/null 2>&1

LOCAL_HASH=$(git rev-parse HEAD)
REMOTE_HASH=$(git rev-parse origin/main)

if [ "$LOCAL_HASH" != "$REMOTE_HASH" ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Ditemukan versi baru di GitHub ($REMOTE_HASH)."
    echo "Memperbarui kode program..."
    git pull origin main
    
    # Cek apakah ada perubahan pada dependensi
    if git diff --name-only "$LOCAL_HASH" HEAD | grep -q "requirements-edge.txt"; then
        echo "Dependensi berubah, memperbarui pip packages..."
        if [ -d "venv" ]; then
            source venv/bin/activate
            pip install -r requirements-edge.txt
        fi
    fi

    # Restart layanan systemd jika aktif
    if systemctl is-active --quiet sitinjau-edge.service; then
        echo "Me-restart layanan sitinjau-edge.service..."
        sudo systemctl restart sitinjau-edge.service
        echo "Layanan berhasil diperbarui dan berjalan kembali!"
    fi
else
    # Kode sudah versi terbaru
    exit 0
fi
