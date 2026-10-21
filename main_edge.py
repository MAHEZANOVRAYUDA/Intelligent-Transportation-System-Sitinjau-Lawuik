"""
Program Utama Edge Computing untuk Raspberry Pi 5 + Hailo-8L NPU
Sistem Monitoring Kemacetan Sitinjau Lauik (Gerbang A / B)
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from src.config import ensure_directories, get_gate_config, get_settings
from src.counting.line_counter import CrossingDirection, LineCounter
from src.detection.detector import VehicleDetector
from src.detection.tracker import SimpleTracker
from src.detection.visualizer import annotate_frame
from src.edge.buffer import EdgeBufferManager
from src.edge.sync_client import EdgeSyncClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
)
logger = logging.getLogger("SitinjauEdge")


class SitinjauEdgeRunner:
    """Runner deteksi & counting mandiri untuk node Raspberry Pi 5 di lapangan."""

    def __init__(
        self,
        gate_id: str = "A",
        rtsp_url: str | None = None,
        server_url: str | None = None,
        interval_menit: int = 5,
        backend: str = "auto",
        preview: bool = False,
    ):
        self.gate_id = gate_id.upper()
        self.interval_menit = max(1, interval_menit)
        self.backend = backend
        self.preview = preview
        self.running = False

        # Muat konfigurasi gerbang
        raw_settings, env = get_settings()
        self.gate_cfg = get_gate_config(self.gate_id)
        if self.gate_cfg is None:
            raise ValueError(f"Konfigurasi untuk gerbang '{self.gate_id}' tidak ditemukan di settings.yaml!")

        # Tentukan URL RTSP (Argumen CLI > Environment > Settings)
        if rtsp_url:
            self.rtsp_url = rtsp_url
        elif self.gate_id == "A" and env.gate_a_rtsp_url:
            self.rtsp_url = env.gate_a_rtsp_url
        elif self.gate_id == "B" and env.gate_b_rtsp_url:
            self.rtsp_url = env.gate_b_rtsp_url
        else:
            self.rtsp_url = raw_settings.get("stream", {}).get("rtsp_url", "")

        # Tentukan URL Server Pusat
        self.server_url = (
            server_url
            or os.environ.get("SERVER_URL")
            or "http://localhost:8000"
        ).rstrip("/")

        # Komponen Deteksi & Tracking
        self.detector = VehicleDetector(backend=self.backend)
        self.tracker = SimpleTracker()
        self.counter = LineCounter(
            line=self.gate_cfg.counting_line,
            entry_direction=self.gate_cfg.entry_direction,
            gate_id=self.gate_id,
            lane_divider=self.gate_cfg.lane_divider,
            inbound_side=self.gate_cfg.inbound_side,
        )

        # Komponen Sinkronisasi Edge & Offline Buffer
        buffer_dir = Path("data")
        buffer_dir.mkdir(parents=True, exist_ok=True)
        self.buffer = EdgeBufferManager(db_path=buffer_dir / f"offline_buffer_{self.gate_id}.db")
        self.sync_client = EdgeSyncClient(
            server_url=self.server_url,
            gate_id=f"GERBANG_{self.gate_id}",
            buffer_manager=self.buffer,
        )

        # Akumulator data per interval
        self.counts_interval = {"motor": 0, "mobil": 0, "bus": 0, "truck": 0}
        self.last_sync_time = time.time()
        self.frame_count = 0
        self.fps_meter = 0.0

    def start(self) -> None:
        logger.info("=== Memulai Node Edge Sitinjau Lauik ===")
        logger.info("Gerbang        : %s (%s)", self.gate_id, self.gate_cfg.name)
        logger.info("RTSP Stream    : %s", self.rtsp_url or "Demo/Webcam")
        logger.info("Server Pusat   : %s", self.server_url)
        logger.info("Interval Lapor : %d menit", self.interval_menit)
        logger.info("Backend Model  : %s", self.backend)

        if not self.detector.load():
            logger.error("Gagal memuat detector backend '%s'. Keluar.", self.backend)
            return

        self.running = True
        self._setup_signals()
        self._run_loop()

    def _setup_signals(self) -> None:
        def _handler(signum, frame):
            logger.info("Menerima sinyal terminasi (%s), menghentikan node edge...", signum)
            self.running = False

        signal.signal(signal.SIGINT, _handler)
        signal.signal(signal.SIGTERM, _handler)

    def _open_capture(self) -> cv2.VideoCapture:
        """Membuka koneksi RTSP dengan optimasi buffer size = 1 dan TCP transport untuk anti-lag dan anti-packet-loss."""
        if self.rtsp_url and self.rtsp_url.startswith("rtsp://"):
            os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"
        src = 0 if not self.rtsp_url else self.rtsp_url
        cap = cv2.VideoCapture(src, cv2.CAP_FFMPEG if isinstance(src, str) else cv2.CAP_ANY)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return cap

    def _run_loop(self) -> None:
        reconnect_delay = 3.0
        while self.running:
            logger.info("Mencoba membuka RTSP feed: %s...", self.rtsp_url or "0")
            cap = self._open_capture()

            if not cap.isOpened():
                logger.warning("Gagal koneksi kamera. Coba lagi dalam %.1f detik...", reconnect_delay)
                time.sleep(reconnect_delay)
                continue

            logger.info("Koneksi kamera aktif! Memulai pemrosesan video...")
            prev_time = time.time()

            while self.running:
                ret, frame = cap.read()
                if not ret or frame is None:
                    logger.warning("Stream terputus atau frame kosong. Memulai rekoneksi...")
                    break

                self.frame_count += 1
                now = time.time()
                dt = now - prev_time
                if dt >= 1.0:
                    self.fps_meter = self.frame_count / dt
                    self.frame_count = 0
                    prev_time = now

                # 1. Deteksi Kendaraan (Hailo NPU / Ultralytics)
                detections = self.detector.detect(frame)

                # 2. Tracking Objek (Kalman Filter + Association)
                tracks = self.tracker.update(detections)

                # 3. Hitung Garis Virtual
                events = self.counter.update(tracks)
                for event in events:
                    cls = event.class_name.lower()
                    if cls == "motor":
                        self.counts_interval["motor"] += 1
                    elif cls in ("mobil", "car"):
                        self.counts_interval["mobil"] += 1
                    elif cls == "bus":
                        self.counts_interval["bus"] += 1
                    elif cls in ("truck", "truk"):
                        self.counts_interval["truck"] += 1

                # 4. Periodik Lapor ke Server Pusat
                elapsed = now - self.last_sync_time
                if elapsed >= (self.interval_menit * 60):
                    self._dispatch_interval_report()
                    self.last_sync_time = now

                # 5. Visualisasi Opsional (Hanya jika mode preview diaktifkan)
                if self.preview:
                    annotated = annotate_frame(
                        frame=frame,
                        line=self.gate_cfg.counting_line,
                        tracks=tracks,
                        detections=detections,
                        gate_id=self.gate_id,
                        inference_fps=self.fps_meter,
                        counts_in=self.counter.state.total_in,
                        counts_out=self.counter.state.total_out,
                        lane_divider=self.gate_cfg.lane_divider,
                        inbound_side=self.gate_cfg.inbound_side,
                    )
                    cv2.putText(
                        annotated,
                        f"FPS: {self.fps_meter:.1f} | Buffer: {self.buffer.count()}",
                        (20, 40),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.8,
                        (0, 255, 0),
                        2,
                    )
                    cv2.imshow("Sitinjau Laut - Edge Preview", annotated)
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        self.running = False
                        break

            cap.release()
            if self.preview:
                cv2.destroyAllWindows()
            if self.running:
                time.sleep(reconnect_delay)

        # Kirim sisa akumulasi sebelum keluar
        self._dispatch_interval_report()
        logger.info("Node Edge berhenti dengan aman.")

    def _dispatch_interval_report(self) -> None:
        """Mengirimkan akumulasi hitungan ke server pusat atau menyimpan ke offline buffer."""
        total = sum(self.counts_interval.values())
        logger.info(
            "[DISPATCH] Mengirim akumulasi %d menit (Total %d unit): %s",
            self.interval_menit,
            total,
            self.counts_interval,
        )

        arah = "MENANJAK" if self.gate_cfg.direction == "A_to_B" else "MENURUN"
        ts = datetime.now().isoformat()

        self.sync_client.send_or_buffer(
            arah=arah,
            timestamp=ts,
            motor=self.counts_interval["motor"],
            mobil=self.counts_interval["mobil"],
            bus=self.counts_interval["bus"],
            truk=self.counts_interval["truck"],
            interval_menit=self.interval_menit,
        )

        # Reset akumulator interval
        self.counts_interval = {"motor": 0, "mobil": 0, "bus": 0, "truck": 0}


def main():
    parser = argparse.ArgumentParser(description="Edge Runner Sistem Monitoring Sitinjau Lauik")

    env_gate = os.environ.get("GATE_ID", "A").upper()
    default_gate = env_gate if env_gate in ("A", "B") else "A"
    parser.add_argument("--gate", choices=["A", "B"], default=default_gate, help="Pilihan gerbang (A atau B)")

    parser.add_argument("--rtsp-url", type=str, default=None, help="Override URL RTSP stream CCTV")

    default_server = os.environ.get("SERVER_URL", "http://localhost:8000")
    parser.add_argument("--server-url", type=str, default=default_server, help="Alamat Server Pusat")

    parser.add_argument("--interval", type=int, default=5, help="Interval pengiriman laporan dalam menit (default 5)")

    env_backend = os.environ.get("DETECTION_BACKEND", "auto").lower()
    default_backend = env_backend if env_backend in ("auto", "hailo", "ultralytics") else "auto"
    parser.add_argument("--backend", choices=["auto", "hailo", "ultralytics"], default=default_backend, help="Backend detektor")

    parser.add_argument("--preview", action="store_true", help="Buka jendela visualisasi (debug onsite)")

    args = parser.parse_args()
    ensure_directories()

    runner = SitinjauEdgeRunner(
        gate_id=args.gate,
        rtsp_url=args.rtsp_url,
        server_url=args.server_url,
        interval_menit=args.interval,
        backend=args.backend,
        preview=args.preview,
    )
    runner.start()


if __name__ == "__main__":
    main()
