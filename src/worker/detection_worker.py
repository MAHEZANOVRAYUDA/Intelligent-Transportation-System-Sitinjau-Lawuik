"""Background detection worker."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

import cv2
import numpy as np

from src.analytics.density import RoadOccupancyManager
from src.capture.stream_manager import RTSPStreamManager, StreamRegistry, StreamState
from src.config import get_gate_config, get_settings, persist_gate_calibration
from src.counting.line_counter import CrossingDirection, LineCounter
from src.detection.detector import VehicleDetector
from src.detection.tracker import SimpleTracker
from src.detection.visualizer import annotate_frame, encode_jpeg
from src.storage.database import save_crossing, save_snapshot

logger = logging.getLogger(__name__)


@dataclass
class GateDebugState:
    jpeg: bytes | None = None
    timestamp: float = 0.0
    detections: list[dict] = field(default_factory=list)
    tracks: list[dict] = field(default_factory=list)
    inference_fps: float = 0.0
    counts_in: dict[str, int] = field(default_factory=dict)
    counts_out: dict[str, int] = field(default_factory=dict)
    recent_crossings: list[dict] = field(default_factory=list)
    live_class_counts: dict[str, int] = field(default_factory=dict)
    counting_line: list[int] = field(default_factory=list)
    entry_direction: str = "up"
    lane_divider: list[int] | None = None
    inbound_side: str = "left"
    frame_width: int = 0
    frame_height: int = 0


class DetectionWorker:
    """Worker thread untuk deteksi, tracking, counting, dan analytics."""

    def __init__(
        self,
        stream_registry: StreamRegistry,
        occupancy: RoadOccupancyManager,
        on_update: Callable[[dict], None] | None = None,
        on_debug_update: Callable[[str, dict], None] | None = None,
    ):
        self.registry = stream_registry
        self.occupancy = occupancy
        self.on_update = on_update
        self.on_debug_update = on_debug_update

        self._detector = VehicleDetector()
        self._trackers: dict[str, SimpleTracker] = {}
        self._counters: dict[str, LineCounter] = {}
        self._debug_states: dict[str, GateDebugState] = {}
        self._debug_lock = threading.Lock()

        self._running = False
        self._thread: threading.Thread | None = None
        self._snapshot_interval = 60
        self._last_snapshot = 0.0
        self._process_every_n = 3
        self._frame_skip_counter = 0
        self._infer_times: dict[str, list[float]] = {}

        raw, env = get_settings()
        self._enabled = env.detection_enabled
        tracking = raw.get("tracking", {})
        self._max_distance = float(tracking.get("max_distance", 200))
        self._max_disappeared = int(tracking.get("max_disappeared", 20))
        self._min_hits = int(tracking.get("min_hits", 3))
        self._min_track_age = int(tracking.get("min_track_age", 3))
        self._min_confidence = float(tracking.get("min_count_confidence", 0.20))
        self._jpeg_quality = int(raw.get("stream", {}).get("jpeg_quality", 80))

        gate_b_url = env.gate_b_rtsp_url
        self.occupancy.set_dual_gate_mode(bool(gate_b_url))

    def start(self) -> None:
        if self._running:
            return

        if self._enabled:
            if not self._detector.load():
                logger.warning("Detection disabled — model gagal dimuat")
                self._enabled = False

        for gate_id in self.registry.all():
            gate_cfg = get_gate_config(gate_id)
            if gate_cfg:
                self._trackers[gate_id] = SimpleTracker(
                    max_disappeared=self._max_disappeared,
                    max_distance=self._max_distance,
                    min_hits=self._min_hits,
                )
                self._counters[gate_id] = LineCounter(
                    line=gate_cfg.counting_line,
                    entry_direction=gate_cfg.entry_direction,
                    gate_id=gate_id,
                    min_track_age=self._min_track_age,
                    min_confidence=self._min_confidence,
                    lane_divider=gate_cfg.lane_divider,
                    inbound_side=gate_cfg.inbound_side,
                )
                self._debug_states[gate_id] = GateDebugState()
                self._infer_times[gate_id] = []

        self._running = True
        self._thread = threading.Thread(target=self._loop, name="detection-worker", daemon=True)
        self._thread.start()
        logger.info("Detection worker started (enabled=%s)", self._enabled)

    def stop(self) -> None:
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

    def get_debug_jpeg(self, gate_id: str) -> bytes | None:
        with self._debug_lock:
            state = self._debug_states.get(gate_id)
            return state.jpeg if state else None

    def get_debug_state(self, gate_id: str) -> dict:
        with self._debug_lock:
            state = self._debug_states.get(gate_id)
            if not state:
                return {}
            counter = self._counters.get(gate_id)
            return {
                "timestamp": state.timestamp,
                "inference_fps": round(state.inference_fps, 1),
                "detection_count": len(state.detections),
                "track_count": len(state.tracks),
                "detections": state.detections,
                "tracks": state.tracks,
                "counts_in": state.counts_in,
                "counts_out": state.counts_out,
                "live_class_counts": state.live_class_counts,
                "recent_crossings": state.recent_crossings,
                "counting_line": list(counter.line) if counter else state.counting_line,
                "entry_direction": counter.entry_direction if counter else state.entry_direction,
                "lane_divider": list(counter.lane_divider) if counter and counter.lane_divider else state.lane_divider,
                "inbound_side": counter.inbound_side if counter else state.inbound_side,
                "frame_width": state.frame_width,
                "frame_height": state.frame_height,
            }

    def get_live_class_counts(self) -> dict[str, int]:
        totals = {"motor": 0, "mobil": 0, "bus": 0, "truck": 0}
        with self._debug_lock:
            for dbg in self._debug_states.values():
                for cls, n in dbg.live_class_counts.items():
                    totals[cls] = totals.get(cls, 0) + int(n)
        return totals

    def apply_calibration(
        self,
        gate_id: str,
        counting_line: list[int] | None = None,
        entry_direction: str | None = None,
        lane_divider: list[int] | None = None,
        inbound_side: str | None = None,
        persist: bool = False,
        reset_counts: bool = False,
        reset_tracks: bool = True,
    ) -> dict:
        counter = self._counters.get(gate_id)
        tracker = self._trackers.get(gate_id)
        if counter is None:
            raise KeyError(f"Gerbang {gate_id} tidak aktif")

        if counting_line is not None:
            counter.set_line(counting_line)
        if entry_direction is not None:
            counter.set_entry_direction(entry_direction)
        if lane_divider is not None:
            counter.set_lane_divider(lane_divider)
        if inbound_side is not None:
            counter.set_inbound_side(inbound_side)
        if reset_counts:
            counter.reset_counts()
        if reset_tracks and tracker is not None:
            for track in tracker.tracks.values():
                track.crossed = False

        if persist:
            persist_gate_calibration(
                gate_id,
                counter.line,
                counter.entry_direction,
                lane_divider=counter.lane_divider,
                inbound_side=counter.inbound_side,
            )

        logger.info(
            "Gate %s calibration: line=%s lane=%s dir=%s persist=%s",
            gate_id,
            counter.line,
            counter.lane_divider,
            counter.entry_direction,
            persist,
        )
        return {
            "gate_id": gate_id,
            "counting_line": list(counter.line),
            "entry_direction": counter.entry_direction,
            "lane_divider": list(counter.lane_divider) if counter.lane_divider else None,
            "inbound_side": counter.inbound_side,
            "persisted": persist,
        }

    def _update_debug(
        self,
        gate_id: str,
        frame: np.ndarray,
        *,
        line: list[int],
        detections: list[dict],
        tracks: list,
        inference_fps: float,
        counter: LineCounter,
    ) -> None:
        stable_tracks = [t for t in tracks if t.age >= self._min_hits]
        live_counts: dict[str, int] = {}
        for t in stable_tracks:
            cls = t.stable_class
            live_counts[cls] = live_counts.get(cls, 0) + 1

        annotated = annotate_frame(
            frame,
            line=line,
            tracks=stable_tracks,
            detections=detections,
            gate_id=gate_id,
            inference_fps=inference_fps,
            counts_in=counter.state.total_in,
            counts_out=counter.state.total_out,
            lane_divider=counter.lane_divider,
            inbound_side=counter.inbound_side,
        )
        h, w = annotated.shape[:2]
        max_w = 1280
        if w > max_w:
            scale = max_w / w
            annotated = cv2.resize(annotated, (max_w, int(h * scale)), interpolation=cv2.INTER_AREA)
        jpeg = encode_jpeg(annotated, self._jpeg_quality)

        track_payload = [
            {
                "track_id": t.track_id,
                "class_name": t.stable_class,
                "confidence": round(t.confidence, 2),
                "bbox": t.bbox,
                "age": t.age,
                "crossed": t.crossed,
            }
            for t in stable_tracks
        ]
        det_payload = [
            {
                "class_name": d["class_name"],
                "confidence": round(d["confidence"], 2),
                "bbox": d["bbox"],
            }
            for d in detections
        ]

        debug_data = {
            "gate_id": gate_id,
            "inference_fps": round(inference_fps, 1),
            "detection_count": len(detections),
            "track_count": len(stable_tracks),
            "detections": det_payload,
            "tracks": track_payload,
            "counts_in": dict(counter.state.total_in),
            "counts_out": dict(counter.state.total_out),
            "live_class_counts": live_counts,
            "recent_crossings": counter.recent_events,
            "counting_line": list(counter.line),
            "entry_direction": counter.entry_direction,
            "lane_divider": list(counter.lane_divider) if counter.lane_divider else None,
            "inbound_side": counter.inbound_side,
            "frame_width": int(frame.shape[1]),
            "frame_height": int(frame.shape[0]),
        }

        with self._debug_lock:
            state = self._debug_states[gate_id]
            state.jpeg = jpeg
            state.timestamp = time.time()
            state.detections = det_payload
            state.tracks = track_payload
            state.inference_fps = inference_fps
            state.counts_in = dict(counter.state.total_in)
            state.counts_out = dict(counter.state.total_out)
            state.live_class_counts = live_counts
            state.recent_crossings = counter.recent_events
            state.counting_line = list(counter.line)
            state.entry_direction = counter.entry_direction
            state.lane_divider = list(counter.lane_divider) if counter.lane_divider else None
            state.inbound_side = counter.inbound_side
            state.frame_width = int(frame.shape[1])
            state.frame_height = int(frame.shape[0])

        if self.on_debug_update:
            self.on_debug_update(gate_id, debug_data)

    def _loop(self) -> None:
        while self._running:
            for gate_id, stream in self.registry.all().items():
                if stream.state != StreamState.LIVE:
                    continue

                packet = stream.get_latest_frame()
                if packet.frame is None:
                    continue

                self._frame_skip_counter += 1
                if self._frame_skip_counter % self._process_every_n != 0:
                    continue

                frame = packet.frame
                counter = self._counters.get(gate_id)
                tracker = self._trackers.get(gate_id)

                if not self._enabled or counter is None or tracker is None:
                    continue

                t0 = time.time()
                detections = self._detector.detect(frame)
                infer_ms = time.time() - t0

                times = self._infer_times[gate_id]
                times.append(infer_ms)
                if len(times) > 30:
                    times.pop(0)
                avg_ms = sum(times) / len(times) if times else infer_ms
                inference_fps = 1.0 / avg_ms if avg_ms > 0 else 0.0

                all_tracks = tracker.update(detections)
                events = counter.update(all_tracks)

                for event in events:
                    save_crossing(
                        gate_id=gate_id,
                        direction=event.direction.value,
                        class_name=event.class_name,
                        confidence=event.confidence,
                        track_id=event.track_id,
                    )

                    if event.direction == CrossingDirection.IN:
                        if gate_id == "A":
                            self.occupancy.register_entry(event.class_name, gate="A")
                        elif gate_id == "B":
                            self.occupancy.register_entry(event.class_name, gate="B")
                    else:
                        if gate_id == "B":
                            self.occupancy.register_exit(event.class_name, gate="B")
                        elif gate_id == "A":
                            self.occupancy.register_exit(event.class_name, gate="A")

                self._update_debug(
                    gate_id,
                    frame,
                    line=counter.line,
                    detections=detections,
                    tracks=all_tracks,
                    inference_fps=inference_fps,
                    counter=counter,
                )

            now = time.time()
            if now - self._last_snapshot >= self._snapshot_interval:
                snap = self.occupancy.snapshot_to_dict()
                save_snapshot(snap)
                self._last_snapshot = now
                if self.on_update:
                    self.on_update(snap)

            time.sleep(0.02)

    def reset_runtime(self) -> None:
        """Reset hitungan sesi, occupancy, dan track agar tidak double-count setelah hapus data."""
        for counter in self._counters.values():
            counter.reset_counts()
        for tracker in self._trackers.values():
            tracker.reset()
        self.occupancy.reset()
        logger.info("Runtime counts, occupancy, and tracks reset")

    def get_counter_stats(self) -> dict:
        stats = {}
        for gate_id, counter in self._counters.items():
            stats[gate_id] = {
                "in": counter.state.total_in,
                "out": counter.state.total_out,
            }
        return stats


class MonitoringBroadcaster:
    """Broadcast monitoring data ke WebSocket clients."""

    def __init__(self):
        self._clients: list[asyncio.Queue] = []
        self._latest: dict = {}

    @property
    def latest(self) -> dict:
        return self._latest

    def set_latest(self, data: dict) -> None:
        self._latest = data

    async def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=10)
        self._clients.append(queue)
        if self._latest:
            await queue.put(self._latest)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        if queue in self._clients:
            self._clients.remove(queue)

    async def broadcast(self, data: dict) -> None:
        self._latest = data
        dead = []
        for q in self._clients:
            try:
                q.put_nowait(data)
            except asyncio.QueueFull:
                try:
                    q.get_nowait()
                    q.put_nowait(data)
                except Exception:
                    dead.append(q)
        for q in dead:
            self.unsubscribe(q)


class DebugBroadcaster:
    """Broadcast debug detection data per gate."""

    def __init__(self):
        self._clients: dict[str, list[asyncio.Queue]] = {}

    async def subscribe(self, gate_id: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=5)
        self._clients.setdefault(gate_id, []).append(queue)
        return queue

    def unsubscribe(self, gate_id: str, queue: asyncio.Queue) -> None:
        clients = self._clients.get(gate_id, [])
        if queue in clients:
            clients.remove(queue)

    async def broadcast(self, gate_id: str, data: dict) -> None:
        dead = []
        for q in self._clients.get(gate_id, []):
            try:
                q.put_nowait(data)
            except asyncio.QueueFull:
                try:
                    q.get_nowait()
                    q.put_nowait(data)
                except Exception:
                    dead.append(q)
        for q in dead:
            self.unsubscribe(gate_id, q)
