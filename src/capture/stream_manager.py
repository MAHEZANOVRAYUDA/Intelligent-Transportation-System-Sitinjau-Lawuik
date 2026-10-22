"""Manajer stream RTSP dengan shared frame buffer untuk anti-buffering."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable

import cv2
import numpy as np

from src.config import get_settings, get_stream_config

logger = logging.getLogger(__name__)


class StreamState(str, Enum):
    CONNECTING = "connecting"
    LIVE = "live"
    RECONNECTING = "reconnecting"
    OFFLINE = "offline"


@dataclass
class FramePacket:
    frame: np.ndarray | None
    timestamp: float
    frame_number: int
    state: StreamState


@dataclass
class StreamStats:
    fps_actual: float = 0.0
    frames_read: int = 0
    reconnect_count: int = 0
    last_error: str | None = None
    state: StreamState = StreamState.OFFLINE
    is_live: bool = False


class RTSPStreamManager:
    """
    Single RTSP reader dengan fan-out ke multiple consumer.

    Strategi anti-buffering:
    1. CAP_PROP_BUFFERSIZE = 1 (minimal buffer OpenCV)
    2. Selalu ambil frame terbaru, bukan frame lama dari queue
    3. Consumer live stream baca langsung dari latest frame (tanpa queue)
    4. Detection worker baca frame yang sama (tidak buka koneksi RTSP kedua)
    """

    def __init__(
        self,
        rtsp_url: str,
        gate_id: str,
        on_state_change: Callable[[str, StreamState], None] | None = None,
    ):
        self.rtsp_url = rtsp_url
        self.gate_id = gate_id
        self.on_state_change = on_state_change
        self._cfg = get_stream_config()

        self._lock = threading.Lock()
        self._latest_frame: np.ndarray | None = None
        self._latest_timestamp: float = 0.0
        self._frame_number: int = 0
        self._state = StreamState.OFFLINE
        self._stats = StreamStats()
        self._running = False
        self._thread: threading.Thread | None = None
        self._fps_counter = 0
        self._fps_timer = time.time()

    @property
    def state(self) -> StreamState:
        return self._state

    @property
    def stats(self) -> StreamStats:
        return self._stats

    def start(self) -> None:
        if self._running:
            return
        if not self.rtsp_url:
            logger.warning("Gate %s: RTSP URL kosong, stream tidak dimulai", self.gate_id)
            self._set_state(StreamState.OFFLINE)
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._capture_loop,
            name=f"rtsp-{self.gate_id}",
            daemon=True,
        )
        self._thread.start()
        logger.info("Gate %s: stream manager started", self.gate_id)

    @property
    def is_live(self) -> bool:
        """Cek apakah stream sedang aktif membaca frame dalam beberapa detik terakhir."""
        now = time.time()
        return (
            self._running
            and self._state == StreamState.LIVE
            and self._stats.frames_read > 0
            and (now - self._latest_timestamp <= 4.0)
        )

    @property
    def fps(self) -> float:
        """FPS aktual saat ini, otomatis 0 jika stream tidak sedang aktif."""
        if not self.is_live:
            return 0.0
        return round(self._stats.fps_actual, 1)

    def stop(self) -> None:
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        self._stats.fps_actual = 0.0
        self._stats.is_live = False
        self._set_state(StreamState.OFFLINE)

    def get_latest_frame(self) -> FramePacket:
        with self._lock:
            return FramePacket(
                frame=self._latest_frame.copy() if self._latest_frame is not None else None,
                timestamp=self._latest_timestamp,
                frame_number=self._frame_number,
                state=self._state,
            )

    def get_frame_for_stream(self, target_width: int | None = None, target_height: int | None = None) -> bytes | None:
        """Ambil frame untuk MJPEG stream web — tanpa overlay deteksi."""
        packet = self.get_latest_frame()
        if packet.frame is None:
            return None

        frame = packet.frame
        w = target_width or self._cfg.output_width
        h = target_height or self._cfg.output_height

        if frame.shape[1] != w or frame.shape[0] != h:
            frame = cv2.resize(frame, (w, h), interpolation=cv2.INTER_LINEAR)

        encode_params = [cv2.IMWRITE_JPEG_QUALITY, self._cfg.jpeg_quality]
        ok, buffer = cv2.imencode(".jpg", frame, encode_params)
        return buffer.tobytes() if ok else None

    def _set_state(self, state: StreamState) -> None:
        if self._state != state:
            self._state = state
            self._stats.state = state
            if self.on_state_change:
                self.on_state_change(self.gate_id, state)

    def _open_capture(self) -> cv2.VideoCapture | None:
        if self.rtsp_url and self.rtsp_url.startswith("rtsp://"):
            import os
            os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = (
                "rtsp_transport;tcp|fflags;nobuffer|flags;low_delay|reorder_queue_size;5|max_delay;500000|analyzeduration;1000000|probesize;1000000"
            )
            os.environ["OPENCV_LOG_LEVEL"] = "ERROR"
            os.environ["OPENCV_FFMPEG_LOGLEVEL"] = "8"
            try:
                cv2.setLogLevel(cv2.LOG_LEVEL_ERROR)
            except Exception:
                pass

        cap = cv2.VideoCapture(self.rtsp_url, cv2.CAP_FFMPEG)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, self._cfg.buffer_size)
        cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 10000)
        cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 10000)

        if not cap.isOpened():
            cap.release()
            return None
        return cap

    def _capture_loop(self) -> None:
        attempts = 0
        max_attempts = self._cfg.max_reconnect_attempts

        while self._running:
            self._set_state(StreamState.CONNECTING)
            cap = self._open_capture()

            if cap is None:
                self._stats.last_error = "Gagal membuka stream RTSP"
                self._set_state(StreamState.RECONNECTING)
                attempts += 1
                if max_attempts > 0 and attempts >= max_attempts:
                    self._set_state(StreamState.OFFLINE)
                    break
                time.sleep(self._cfg.reconnect_delay_sec)
                continue

            attempts = 0
            first_frame_read = False

            while self._running:
                ret, frame = cap.read()
                if not ret or frame is None:
                    self._stats.last_error = "Frame read failed"
                    self._stats.fps_actual = 0.0
                    self._stats.is_live = False
                    self._stats.reconnect_count += 1
                    logger.warning("Gate %s: frame read failed, reconnecting...", self.gate_id)
                    break

                now = time.time()
                with self._lock:
                    self._latest_frame = frame
                    self._latest_timestamp = now
                    self._frame_number += 1
                    self._stats.frames_read += 1

                if not first_frame_read:
                    first_frame_read = True
                    self._stats.is_live = True
                    self._set_state(StreamState.LIVE)
                    logger.info("Gate %s: RTSP stream live and receiving frames", self.gate_id)

                self._fps_counter += 1
                if now - self._fps_timer >= 1.0:
                    self._stats.fps_actual = self._fps_counter / (now - self._fps_timer)
                    self._fps_counter = 0
                    self._fps_timer = now

            cap.release()
            self._stats.fps_actual = 0.0
            self._stats.is_live = False
            if self._running:
                self._set_state(StreamState.RECONNECTING)
                time.sleep(self._cfg.reconnect_delay_sec)

        self._stats.fps_actual = 0.0
        self._stats.is_live = False
        self._set_state(StreamState.OFFLINE)


class StreamRegistry:
    """Registry untuk semua stream manager aktif."""

    def __init__(self):
        self._streams: dict[str, RTSPStreamManager] = {}
        self._lock = threading.Lock()

    def register(self, manager: RTSPStreamManager) -> None:
        with self._lock:
            self._streams[manager.gate_id] = manager

    def get(self, gate_id: str) -> RTSPStreamManager | None:
        with self._lock:
            return self._streams.get(gate_id)

    def all(self) -> dict[str, RTSPStreamManager]:
        with self._lock:
            return dict(self._streams)

    def get_status_dict(self) -> dict[str, dict]:
        """Status terkini semua gerbang (A & B), baik yang terdaftar maupun belum."""
        _, env = get_settings()
        configured_urls = {
            "A": env.gate_a_rtsp_url,
            "B": env.gate_b_rtsp_url,
        }
        res = {}
        for gid in ["A", "B"]:
            sm = self.get(gid)
            url = configured_urls.get(gid, "")
            if not url or sm is None:
                res[gid] = {
                    "state": "unconfigured",
                    "configured": False,
                    "is_live": False,
                    "fps": 0.0,
                    "frames": 0,
                }
            else:
                is_live = sm.is_live
                res[gid] = {
                    "state": sm.state.value if is_live else ("connecting" if sm.state in (StreamState.CONNECTING, StreamState.RECONNECTING) else sm.state.value),
                    "configured": True,
                    "is_live": is_live,
                    "fps": sm.fps,
                    "frames": sm.stats.frames_read,
                    "reconnect_count": sm.stats.reconnect_count,
                }
        return res

    def start_all(self) -> None:
        for manager in self.all().values():
            manager.start()

    def stop_all(self) -> None:
        for manager in self.all().values():
            manager.stop()
