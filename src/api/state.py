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
        "counts_in": {"motor": 0, "mobil": 0, "bus": 0, "truck": 0},
        "counts_out": {"motor": 0, "mobil": 0, "bus": 0, "truck": 0},
        "last_processed_in": {"motor": 0, "mobil": 0, "bus": 0, "truck": 0},
        "last_processed_out": {"motor": 0, "mobil": 0, "bus": 0, "truck": 0},
        "buffer_count": 0,
    },
    "B": {
        "status": "offline",
        "last_seen": None,
        "backend": None,
        "fps": 0.0,
        "counts": {"in": 0, "out": 0},
        "counts_in": {"motor": 0, "mobil": 0, "bus": 0, "truck": 0},
        "counts_out": {"motor": 0, "mobil": 0, "bus": 0, "truck": 0},
        "last_processed_in": {"motor": 0, "mobil": 0, "bus": 0, "truck": 0},
        "last_processed_out": {"motor": 0, "mobil": 0, "bus": 0, "truck": 0},
        "buffer_count": 0,
    },
}

# Menyimpan kalibrasi runtime sementara untuk edge node
edge_calibrations: dict[str, dict] = {}


def is_gate_edge(gate_id: str, env: Any) -> bool:
    """Mengecek apakah gerbang (A atau B) beroperasi dalam mode Edge Node (RPi 5 + Hailo)."""
    gid = gate_id.upper()
    mode = getattr(env, f"gate_{gid.lower()}_mode", "auto").lower()
    edge_url = getattr(env, f"gate_{gid.lower()}_edge_url", "")
    node_status = edge_nodes.get(gid, {}).get("status")
    return mode == "edge" or bool(edge_url) or (node_status == "online")
