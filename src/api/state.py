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
