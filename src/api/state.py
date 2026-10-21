"""Shared application state — hindari circular import."""

from __future__ import annotations

from src.analytics.density import RoadOccupancyManager
from src.capture.stream_manager import StreamRegistry
from src.worker.detection_worker import DebugBroadcaster, DetectionWorker, MonitoringBroadcaster

stream_registry = StreamRegistry()
occupancy_manager = RoadOccupancyManager()
broadcaster = MonitoringBroadcaster()
debug_broadcaster = DebugBroadcaster()
detection_worker: DetectionWorker | None = None

# Tracking status Edge Node per gerbang (Raspberry Pi 5 + Hailo-8L)
edge_nodes: dict[str, dict] = {
    "A": {
        "status": "offline",
        "last_seen": None,
        "backend": None,
        "fps": 0.0,
        "counts": {"in": 0, "out": 0},
        "buffer_count": 0,
    },
    "B": {
        "status": "offline",
        "last_seen": None,
        "backend": None,
        "fps": 0.0,
        "counts": {"in": 0, "out": 0},
        "buffer_count": 0,
    },
}

# Menyimpan kalibrasi runtime sementara untuk edge node
edge_calibrations: dict[str, dict] = {}
