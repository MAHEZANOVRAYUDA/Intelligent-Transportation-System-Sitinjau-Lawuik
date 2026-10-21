"""
Program Utama Edge Computing untuk Raspberry Pi 5 + Hailo-8L NPU
Sistem Monitoring Kemacetan Sitinjau Lauik (Gerbang A / B)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
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



class EdgeStreamHolder:
    """Buffer frame gambar JPEG teranotasi dan metadata performa NPU untuk web streaming."""

    def __init__(self):
        self._lock = threading.Lock()
        self._latest_jpeg: bytes | None = None
        self._metadata: dict = {}

    def update(self, jpeg: bytes, metadata: dict) -> None:
        with self._lock:
            self._latest_jpeg = jpeg
            self._metadata = metadata

    def get_frame(self) -> bytes | None:
        with self._lock:
            return self._latest_jpeg

    def get_metadata(self) -> dict:
        with self._lock:
            return self._metadata.copy()


class EdgeHTTPHandler(BaseHTTPRequestHandler):
    """Handler HTTP ringan untuk stream MJPEG dan dashboard onsite Raspberry Pi."""

    stream_holder: EdgeStreamHolder | None = None

    def log_message(self, format: str, *args) -> None:
        # Menekan log akses HTTP agar log inferensi terminal tetap bersih
        pass

    def do_GET(self) -> None:
        if self.path in ("/", "/index.html"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            meta = self.stream_holder.get_metadata() if self.stream_holder else {}
            gate = meta.get("gate", "Edge")
            backend = meta.get("backend", "Hailo-8L")
            html = f"""<!DOCTYPE html>
<html lang="id">
<head>
  <meta charset="utf-8">
  <title>Sitinjau Edge — Gerbang {gate}</title>
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <style>
    :root {{
      --bg: #090d16;
      --card: #131b2e;
      --accent: #2563eb;
      --text: #f1f5f9;
      --text-muted: #94a3b8;
      --success: #10b981;
      --border: rgba(255, 255, 255, 0.08);
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      padding: 1.5rem;
      display: flex;
      flex-direction: column;
      align-items: center;
      min-height: 100vh;
    }}
    .header {{
      width: 100%;
      max-width: 960px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 1.25rem;
      padding: 0.875rem 1.25rem;
      background: var(--card);
      border-radius: 12px;
      border: 1px solid var(--border);
    }}
    .badge {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 4px 12px;
      border-radius: 9999px;
      font-size: 0.8rem;
      font-weight: 600;
      background: rgba(16, 185, 129, 0.15);
      color: var(--success);
    }}
    .badge-dot {{
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: var(--success);
      box-shadow: 0 0 8px var(--success);
      animation: pulse 2s infinite;
    }}
    @keyframes pulse {{
      0%, 100% {{ opacity: 1; }}
      50% {{ opacity: 0.4; }}
    }}
    .video-container {{
      width: 100%;
      max-width: 960px;
      position: relative;
      background: #000;
      border-radius: 16px;
      overflow: hidden;
      border: 1px solid var(--border);
      box-shadow: 0 20px 40px rgba(0, 0, 0, 0.6);
      aspect-ratio: 16 / 9;
      display: flex;
      align-items: center;
      justify-content: center;
    }}
    .video-container img {{
      width: 100%;
      height: 100%;
      object-fit: contain;
    }}
    .stats-grid {{
      width: 100%;
      max-width: 960px;
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
      gap: 1rem;
      margin-top: 1.25rem;
    }}
    .stat-card {{
      background: var(--card);
      padding: 1rem 1.25rem;
      border-radius: 12px;
      border: 1px solid var(--border);
    }}
    .stat-title {{
      font-size: 0.8rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--text-muted);
      margin-bottom: 0.35rem;
    }}
    .stat-value {{
      font-size: 1.6rem;
      font-weight: 700;
      color: #fff;
    }}
  </style>
</head>
<body>
  <div class="header">
    <div>
      <h2 style="font-size: 1.25rem; font-weight: 700;">Sitinjau Lauik — Edge Node Gerbang {gate}</h2>
      <p style="font-size: 0.85rem; color: var(--text-muted);">Hardware: Raspberry Pi 5 + Hailo-8L NPU ({backend})</p>
    </div>
    <div class="badge">
      <span class="badge-dot"></span>
      <span>NPU ACTIVE</span>
    </div>
  </div>
  <div class="video-container">
    <img src="/stream" alt="Live Edge NPU Stream">
  </div>
  <div class="stats-grid">
    <div class="stat-card">
      <div class="stat-title">NPU Inference FPS</div>
      <div class="stat-value" id="val-fps">-- FPS</div>
    </div>
    <div class="stat-card">
      <div class="stat-title">Total Kendaraan Masuk</div>
      <div class="stat-value" id="val-in">--</div>
    </div>
    <div class="stat-card">
      <div class="stat-title">Total Kendaraan Keluar</div>
      <div class="stat-value" id="val-out">--</div>
    </div>
    <div class="stat-card">
      <div class="stat-title">Buffer Antrean Offline</div>
      <div class="stat-value" id="val-buf">0 rekaman</div>
    </div>
  </div>
  <script>
    async function updateStats() {{
      try {{
        const res = await fetch('/api/status');
        if (res.ok) {{
          const d = await res.json();
          document.getElementById('val-fps').textContent = (d.fps || 0).toFixed(1) + ' FPS';
          document.getElementById('val-in').textContent = d.counts_in ?? 0;
          document.getElementById('val-out').textContent = d.counts_out ?? 0;
          document.getElementById('val-buf').textContent = (d.buffer_count ?? 0) + ' rekaman';
        }}
      }} catch (e) {{}}
    }}
    setInterval(updateStats, 1000);
    updateStats();
  </script>
</body>
</html>"""
            self.wfile.write(html.encode("utf-8"))
        elif self.path == "/api/status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            meta = self.stream_holder.get_metadata() if self.stream_holder else {}
            self.wfile.write(json.dumps(meta).encode("utf-8"))
        elif self.path == "/stream":
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Cache-Control", "no-cache, private")
            self.send_header("Pragma", "no-cache")
            self.end_headers()
            try:
                while True:
                    frame = self.stream_holder.get_frame() if self.stream_holder else None
                    if frame:
                        self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n")
                    time.sleep(0.04)
            except (BrokenPipeError, ConnectionResetError):
                pass
        else:
            self.send_response(404)
            self.end_headers()


def start_edge_web_server(stream_holder: EdgeStreamHolder, port: int = 8080) -> HTTPServer:
    """Menjalankan HTTP server MJPEG di thread terpisah."""
    EdgeHTTPHandler.stream_holder = stream_holder
    server = HTTPServer(("0.0.0.0", port), EdgeHTTPHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    logger.info("Edge Live Web Stream aktif di http://0.0.0.0:%d", port)
    return server


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
        web_stream: bool = False,
        web_port: int = 8080,
    ):
        self.gate_id = gate_id.upper()
        self.interval_menit = max(1, interval_menit)
        self.backend = backend
        self.preview = preview
        self.web_stream = web_stream
        self.web_port = web_port
        self.stream_holder = EdgeStreamHolder() if (self.web_stream or self.preview) else None
        self.running = False
        self.last_heartbeat_time = 0.0

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

        if self.web_stream and self.stream_holder:
            start_edge_web_server(self.stream_holder, self.web_port)

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
        """Membuka koneksi RTSP dengan optimasi TCP transport, nobuffer, low-delay, dan peredaman log spam POC."""
        if self.rtsp_url and self.rtsp_url.startswith("rtsp://"):
            os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = (
                "rtsp_transport;tcp|fflags;nobuffer|flags;low_delay|reorder_queue_size;0|analyzeduration;1000000|probesize;1000000"
            )
            os.environ["OPENCV_LOG_LEVEL"] = "ERROR"
            os.environ["OPENCV_FFMPEG_LOGLEVEL"] = "16"
            try:
                cv2.setLogLevel(cv2.LOG_LEVEL_ERROR)
            except Exception:
                pass

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

            logger.info("Koneksi kamera aktif! Menstabilkan decoder stream...")
            # Buang beberapa frame awal agar paket I-frame (SPS/PPS) sinkron dan tidak menimbulkan artefak POC
            for _ in range(3):
                cap.grab()

            logger.info("Decoder stabil! Memulai pemrosesan deteksi video...")
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

                # 5. Periodik Heartbeat ke Server Pusat (setiap 15 detik)
                if (now - self.last_heartbeat_time) >= 15.0:
                    self.last_heartbeat_time = now
                    active_backend = getattr(self.detector, "active_backend", self.backend)
                    threading.Thread(
                        target=self.sync_client.send_heartbeat,
                        kwargs={
                            "backend": active_backend,
                            "fps": self.fps_meter,
                            "total_in": self.counter.state.total_in,
                            "total_out": self.counter.state.total_out,
                            "buffer_count": self.buffer.count(),
                        },
                        daemon=True,
                    ).start()

                # 6. Visualisasi & Web Stream MJPEG
                if self.stream_holder or self.preview:
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
                        f"RPi5 + Hailo-8L | FPS: {self.fps_meter:.1f} | Buffer: {self.buffer.count()}",
                        (20, 35),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.7,
                        (0, 255, 0),
                        2,
                    )
                    if self.stream_holder:
                        ret_enc, jpeg_bytes = cv2.imencode(
                            ".jpg", annotated, [int(cv2.IMWRITE_JPEG_QUALITY), 75]
                        )
                        if ret_enc:
                            self.stream_holder.update(
                                jpeg_bytes.tobytes(),
                                {
                                    "gate": self.gate_id,
                                    "backend": getattr(self.detector, "active_backend", self.backend),
                                    "fps": round(self.fps_meter, 1),
                                    "counts_in": self.counter.state.total_in,
                                    "counts_out": self.counter.state.total_out,
                                    "buffer_count": self.buffer.count(),
                                },
                            )
                    if self.preview:
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
    parser.add_argument("--web-stream", action="store_true", help="Aktifkan web streaming server MJPEG di port 8080 (http://<ip-rpi>:8080)")
    parser.add_argument("--web-port", type=int, default=8080, help="Port untuk web streaming server MJPEG (default 8080)")

    args = parser.parse_args()
    ensure_directories()

    runner = SitinjauEdgeRunner(
        gate_id=args.gate,
        rtsp_url=args.rtsp_url,
        server_url=args.server_url,
        interval_menit=args.interval,
        backend=args.backend,
        preview=args.preview,
        web_stream=args.web_stream,
        web_port=args.web_port,
    )
    runner.start()


if __name__ == "__main__":
    main()
