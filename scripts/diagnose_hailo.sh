#!/usr/bin/env bash
# ==============================================================================
# Script Diagnostik Lengkap Hardware & Driver NPU Hailo-8L pada Raspberry Pi 5
# ==============================================================================

echo "=========================================================="
echo "    DIAGNOSTIK SITINJAU EDGE - HAILO-8L NPU SYSTEM CHECK   "
echo "=========================================================="
date
echo ""

echo "--- [1] Cek Keberadaan Device Node di /dev ---"
ls -la /dev/hailo* 2>&1 || echo "Tidak ada /dev/hailo*"
echo ""

echo "--- [2] Cek Proses yang Sedang Mengunci /dev/hailo0 ---"
sudo lsof /dev/hailo0 2>&1 || echo "lsof: tidak ada proses aktif"
sudo fuser -v /dev/hailo0 2>&1 || echo "fuser: tidak ada proses aktif"
echo ""

echo "--- [3] Cek Modul Kernel PCIe (lsmod) ---"
lsmod | grep hailo || echo "Modul hailo_pci tidak ter-load!"
echo ""

echo "--- [4] Cek Status Hardware via HailoRT CLI ---"
echo "[A] hailortcli scan:"
hailortcli scan 2>&1 || echo "hailortcli scan gagal"
echo ""
echo "[B] hailortcli fw-control identify:"
hailortcli fw-control identify 2>&1 || echo "fw-control identify gagal"
echo ""

echo "--- [5] Cek Versi Paket Software Hailo (dpkg) ---"
dpkg -l | grep -i hailo || echo "Tidak ada paket hailo yang terdaftar di dpkg"
echo ""

echo "--- [6] Cek Kernel Log Terbaru untuk Hailo & PCIe (dmesg) ---"
sudo dmesg | grep -iE "hailo|pcie" | tail -n 20 || echo "Tidak ada log dmesg"
echo ""

echo "--- [7] Uji Inisialisasi Python HailoRT Minimal ---"
PYTHON_BIN="./venv/bin/python3"
if [ ! -f "$PYTHON_BIN" ]; then
    PYTHON_BIN="python3"
fi

$PYTHON_BIN - << 'EOF'
import sys
try:
    import hailo_platform
    from hailo_platform import VDevice, Device
    print(f"hailo_platform version: {getattr(hailo_platform, '__version__', 'unknown')}")
    
    # Tes 1: Device scan
    devices = Device.scan()
    print(f"Device.scan() result: {devices}")

    # Tes 2: VDevice polos tanpa params
    try:
        v = VDevice()
        print("SUCCESS: VDevice() polos berhasil dialokasikan!")
        v.release()
    except Exception as e:
        print(f"FAILED VDevice(): {e}")

    # Tes 3: VDevice dengan explicit params device_count=1
    try:
        p = VDevice.create_params()
        p.device_count = 1
        v2 = VDevice(p)
        print("SUCCESS: VDevice(device_count=1) berhasil dialokasikan!")
        v2.release()
    except Exception as e:
        print(f"FAILED VDevice(device_count=1): {e}")

except Exception as err:
    print(f"Python test error: {err}")
EOF

echo ""
echo "=========================================================="
echo " Diagnostik Selesai! Silakan salin atau foto output di atas."
echo "=========================================================="
