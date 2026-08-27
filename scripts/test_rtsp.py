"""Test koneksi RTSP ke kamera Bardi."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import cv2
from dotenv import load_dotenv
import os

load_dotenv(ROOT / ".env")

RTSP_URL = os.getenv("GATE_A_RTSP_URL", "")

def main():
    print(f"Testing RTSP: {RTSP_URL[:30]}...")
    cap = cv2.VideoCapture(RTSP_URL, cv2.CAP_FFMPEG)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    if not cap.isOpened():
        print("FAIL: Tidak bisa membuka stream RTSP")
        print("Pastikan PC terhubung ke jaringan yang sama dengan kamera (192.168.50.x)")
        return 1

    print("OK: Stream terbuka")
    ret, frame = cap.read()
    if ret and frame is not None:
        h, w = frame.shape[:2]
        print(f"OK: Frame diterima — {w}x{h}")
        out = ROOT / "data" / "frames" / "test_frame.jpg"
        out.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(out), frame)
        print(f"OK: Frame disimpan ke {out}")
    else:
        print("FAIL: Tidak bisa membaca frame")
        cap.release()
        return 1

    cap.release()
    print("Test selesai — kamera siap digunakan")
    return 0

if __name__ == "__main__":
    sys.exit(main())
