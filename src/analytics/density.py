"""Perhitungan kapasitas jalan dan status lalu lintas."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

from src.config import get_road_capacity, get_settings, get_traffic_thresholds, get_vehicle_lengths


class TrafficLevel(str, Enum):
    LANCAR = "lancar"
    PADAT = "padat"
    MACET = "macet"


@dataclass
class VehicleCount:
    motor: int = 0
    mobil: int = 0
    bus: int = 0
    truck: int = 0

    def to_dict(self) -> dict[str, int]:
        return {"motor": self.motor, "mobil": self.mobil, "bus": self.bus, "truck": self.truck}

    def total(self) -> int:
        return self.motor + self.mobil + self.bus + self.truck


@dataclass
class OnRoadVehicle:
    class_name: str
    entered_at: datetime
    gate: str


@dataclass
class TrafficSnapshot:
    timestamp: datetime
    on_road: VehicleCount
    volume_used_meter_lajur: float
    capacity_meter_lajur: float
    utilization_percent: float
    status: TrafficLevel
    counts_in: VehicleCount
    counts_out: VehicleCount


class RoadOccupancyManager:
    """
    Mengelola estimasi kendaraan di jalan A→B dan menghitung % kapasitas.

    Mode dual-gate: masuk di A, keluar di B.
    Mode single-gate: kendaraan dihapus setelah estimasi waktu tempuh.
    """

    def __init__(self):
        self._lengths = get_vehicle_lengths()
        self._capacity = get_road_capacity()
        self._thresholds = get_traffic_thresholds()
        raw, _ = get_settings()
        self._transit_sec = int(raw["transit"]["estimated_transit_sec"])

        self._on_road: list[OnRoadVehicle] = []
        self._counts_in = VehicleCount()
        self._counts_out = VehicleCount()
        self._dual_gate_mode = False

    def set_dual_gate_mode(self, enabled: bool) -> None:
        self._dual_gate_mode = enabled

    def register_entry(self, class_name: str, gate: str = "A") -> None:
        self._on_road.append(OnRoadVehicle(class_name=class_name, entered_at=datetime.now(), gate=gate))
        attr = class_name if hasattr(self._counts_in, class_name) else None
        if attr:
            setattr(self._counts_in, class_name, getattr(self._counts_in, class_name) + 1)

    def register_exit(self, class_name: str, gate: str = "B") -> None:
        for i, v in enumerate(self._on_road):
            if v.class_name == class_name:
                self._on_road.pop(i)
                if hasattr(self._counts_out, class_name):
                    setattr(self._counts_out, class_name, getattr(self._counts_out, class_name) + 1)
                return

    def reset(self) -> None:
        self._on_road.clear()
        self._counts_in = VehicleCount()
        self._counts_out = VehicleCount()

    def _expire_transit(self) -> None:
        if self._dual_gate_mode:
            return
        cutoff = datetime.now() - timedelta(seconds=self._transit_sec)
        self._on_road = [v for v in self._on_road if v.entered_at > cutoff]

    def _count_on_road(self) -> VehicleCount:
        counts = VehicleCount()
        for v in self._on_road:
            setattr(counts, v.class_name, getattr(counts, v.class_name) + 1)
        return counts

    def calculate_volume_used(self) -> float:
        """Total meter-lajur terpakai = Σ (jumlah_kendaraan × panjang_kendaraan)."""
        counts = self._count_on_road()
        total = 0.0
        for cls, length in self._lengths.items():
            total += getattr(counts, cls) * length
        return total

    def get_utilization_percent(self) -> float:
        used = self.calculate_volume_used()
        if self._capacity <= 0:
            return 0.0
        return min((used / self._capacity) * 100, 100.0)

    def get_status(self, utilization: float | None = None) -> TrafficLevel:
        pct = utilization if utilization is not None else self.get_utilization_percent()
        if pct <= self._thresholds.lancar_max:
            return TrafficLevel.LANCAR
        if pct <= self._thresholds.padat_max:
            return TrafficLevel.PADAT
        return TrafficLevel.MACET

    def get_snapshot(self) -> TrafficSnapshot:
        self._expire_transit()
        on_road = self._count_on_road()
        volume_used = self.calculate_volume_used()
        utilization = self.get_utilization_percent()

        return TrafficSnapshot(
            timestamp=datetime.now(),
            on_road=on_road,
            volume_used_meter_lajur=round(volume_used, 2),
            capacity_meter_lajur=self._capacity,
            utilization_percent=round(utilization, 2),
            status=self.get_status(utilization),
            counts_in=VehicleCount(**self._counts_in.to_dict()),
            counts_out=VehicleCount(**self._counts_out.to_dict()),
        )

    def snapshot_to_dict(self, snap: TrafficSnapshot | None = None) -> dict:
        s = snap or self.get_snapshot()
        return {
            "timestamp": s.timestamp.isoformat(),
            "on_road": s.on_road.to_dict(),
            "on_road_total": s.on_road.total(),
            "volume_used_meter_lajur": s.volume_used_meter_lajur,
            "capacity_meter_lajur": s.capacity_meter_lajur,
            "utilization_percent": s.utilization_percent,
            "status": s.status.value,
            "counts_in": s.counts_in.to_dict(),
            "counts_out": s.counts_out.to_dict(),
        }
