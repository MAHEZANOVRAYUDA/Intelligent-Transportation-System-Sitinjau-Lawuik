"""Virtual line crossing counter."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum

from src.detection.tracker import Track

logger = logging.getLogger(__name__)


class CrossingDirection(str, Enum):
    IN = "in"
    OUT = "out"


@dataclass
class CrossingEvent:
    track_id: int
    class_name: str
    direction: CrossingDirection
    confidence: float


@dataclass
class LineCounterState:
    total_in: dict[str, int] = field(default_factory=lambda: {"motor": 0, "mobil": 0, "bus": 0, "truck": 0})
    total_out: dict[str, int] = field(default_factory=lambda: {"motor": 0, "mobil": 0, "bus": 0, "truck": 0})


@dataclass
class _PendingCrossing:
    track_id: int
    class_name: str
    direction: CrossingDirection
    confidence: float


class LineCounter:
    """
    Menghitung kendaraan yang melewati garis virtual.

    Ambang umur/confidence hampir tidak menahan simpan: bbox yang sudah
    menyeberang garis dikomit segera. Filter lajur default non-ketat agar
    deteksi benar di overlay tidak terbuang hanya karena sisi cyan.
    """

    def __init__(
        self,
        line: list[int],
        entry_direction: str = "up",
        gate_id: str = "A",
        min_track_age: int = 1,
        min_confidence: float = 0.05,
        lane_divider: list[int] | None = None,
        inbound_side: str = "left",
        strict_lane_filter: bool = False,
    ):
        self.line = line
        self.entry_direction = entry_direction
        self.gate_id = gate_id
        self.min_track_age = min_track_age
        self.min_confidence = min_confidence
        self.lane_divider = lane_divider
        self.inbound_side = inbound_side
        self.strict_lane_filter = strict_lane_filter
        self.state = LineCounterState()
        self._prev_side: dict[int, str] = {}
        self._prev_point: dict[int, tuple[float, float]] = {}
        self._pending: dict[int, _PendingCrossing] = {}
        self._recent_events: list[dict] = []

    @property
    def recent_events(self) -> list[dict]:
        return list(self._recent_events[-20:])

    def set_line(self, line: list[int]) -> None:
        if len(line) != 4:
            raise ValueError("counting_line harus [x1, y1, x2, y2]")
        self.line = [int(v) for v in line]
        self._clear_motion_state()

    def set_entry_direction(self, direction: str) -> None:
        if direction not in ("up", "down"):
            raise ValueError("entry_direction harus 'up' atau 'down'")
        self.entry_direction = direction
        self._clear_motion_state()

    def set_lane_divider(self, line: list[int] | None) -> None:
        if line is None:
            self.lane_divider = None
            return
        if len(line) != 4:
            raise ValueError("lane_divider harus [x1, y1, x2, y2]")
        self.lane_divider = [int(v) for v in line]
        self._clear_motion_state()

    def set_inbound_side(self, side: str) -> None:
        if side not in ("left", "right"):
            raise ValueError("inbound_side harus 'left' atau 'right'")
        self.inbound_side = side
        self._clear_motion_state()

    def reset_counts(self) -> None:
        self.state = LineCounterState()
        self._recent_events.clear()
        self._clear_motion_state()

    def _clear_motion_state(self) -> None:
        self._prev_side.clear()
        self._prev_point.clear()
        self._pending.clear()

    @staticmethod
    def _counting_point(track: Track) -> tuple[float, float]:
        """Pusat bbox: lebih stabil untuk arah IN/OUT daripada tepi bawah (bbox membesar saat mendekat)."""
        x1, y1, x2, y2 = track.bbox
        return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)

    @staticmethod
    def _segments_intersect(
        a1: tuple[float, float],
        a2: tuple[float, float],
        b1: tuple[float, float],
        b2: tuple[float, float],
    ) -> bool:
        def orient(p, q, r) -> float:
            return (q[1] - p[1]) * (r[0] - q[0]) - (q[0] - p[0]) * (r[1] - q[1])

        def on_seg(p, q, r) -> bool:
            return (
                min(p[0], r[0]) - 1e-6 <= q[0] <= max(p[0], r[0]) + 1e-6
                and min(p[1], r[1]) - 1e-6 <= q[1] <= max(p[1], r[1]) + 1e-6
            )

        o1 = orient(a1, a2, b1)
        o2 = orient(a1, a2, b2)
        o3 = orient(b1, b2, a1)
        o4 = orient(b1, b2, a2)

        if (o1 > 0 and o2 < 0 or o1 < 0 and o2 > 0) and (o3 > 0 and o4 < 0 or o3 < 0 and o4 > 0):
            return True
        if abs(o1) < 1e-9 and on_seg(a1, b1, a2):
            return True
        if abs(o2) < 1e-9 and on_seg(a1, b2, a2):
            return True
        if abs(o3) < 1e-9 and on_seg(b1, a1, b2):
            return True
        if abs(o4) < 1e-9 and on_seg(b1, a2, b2):
            return True
        return False

    def _point_side(self, px: float, py: float) -> str:
        x1, y1, x2, y2 = self.line
        cross = (x2 - x1) * (py - y1) - (y2 - y1) * (px - x1)
        return "above" if cross >= 0 else "below"

    def _lane_region(self, px: float, py: float) -> str | None:
        """Kiri/kanan garis pemisah lajur. None jika divider belum dikonfigurasi."""
        if not self.lane_divider or len(self.lane_divider) != 4:
            return None
        x1, y1, x2, y2 = self.lane_divider
        cross = (x2 - x1) * (py - y1) - (y2 - y1) * (px - x1)
        return "left" if cross >= 0 else "right"

    def _lane_distance(self, px: float, py: float) -> float:
        if not self.lane_divider or len(self.lane_divider) != 4:
            return 0.0
        x1, y1, x2, y2 = self.lane_divider
        dx, dy = x2 - x1, y2 - y1
        length = (dx * dx + dy * dy) ** 0.5
        if length < 1e-6:
            return 0.0
        cross = dx * (py - y1) - dy * (px - x1)
        return abs(cross) / length

    def _direction_from_lane(self, px: float, py: float) -> CrossingDirection | None:
        """Arah dari sisi lajur jika kendaraan jelas di kiri/kanan garis cyan."""
        region = self._lane_region(px, py)
        if region is None:
            return None
        if self._lane_distance(px, py) < 48:
            return None
        if region == self.inbound_side:
            return CrossingDirection.IN
        return CrossingDirection.OUT

    def _direction_from_motion(
        self,
        prev_pt: tuple[float, float],
        curr_pt: tuple[float, float],
    ) -> CrossingDirection | None:
        """Arah dari perpindahan pusat bbox, selaras dengan entry_direction."""
        prev_side = self._point_side(*prev_pt)
        curr_side = self._point_side(*curr_pt)
        from_sides = self._direction_from_sides(prev_side, curr_side)
        if from_sides is not None:
            return from_sides
        dx = curr_pt[0] - prev_pt[0]
        dy = curr_pt[1] - prev_pt[1]
        if abs(dx) + abs(dy) < 4.0:
            return None
        x1, y1, x2, y2 = self.line
        # Komponen gerak tegak lurus garis (tanda sama dengan _point_side).
        nx, ny = -(y2 - y1), (x2 - x1)
        progress = dx * nx + dy * ny
        if abs(progress) < 1e-6:
            return None
        going_above = progress > 0
        if self.entry_direction == "up":
            return CrossingDirection.IN if going_above else CrossingDirection.OUT
        return CrossingDirection.IN if not going_above else CrossingDirection.OUT

    def _resolve_direction(
        self,
        prev_pt: tuple[float, float] | None,
        curr_pt: tuple[float, float],
        prev_side: str | None,
        curr_side: str,
    ) -> CrossingDirection | None:
        """
        Menentukan arah penyeberangan (IN/OUT) dengan hierarki kepastian:
        1. Posisi lajur (lane divider) jika kendaraan berada jelas di sisi jalur.
        2. Vektor gerak centroid (motion trajectory) terhadap garis penyeberang.
        3. Transisi sisi (above -> below atau sebaliknya) sebagai fallback.
        """
        lane_dir = self._direction_from_lane(*curr_pt)
        if lane_dir is not None:
            return lane_dir

        if prev_pt is not None:
            motion_dir = self._direction_from_motion(prev_pt, curr_pt)
            if motion_dir is not None:
                return motion_dir

        if prev_side is not None:
            return self._direction_from_sides(prev_side, curr_side)

        return None

    def _direction_allowed(self, direction: CrossingDirection, cx: float, cy: float) -> bool:
        if not self.strict_lane_filter:
            return True
        region = self._lane_region(cx, cy)
        if region is None:
            return True
        if direction == CrossingDirection.IN:
            return region == self.inbound_side
        return region != self.inbound_side

    def _direction_from_sides(self, prev: str, curr: str) -> CrossingDirection | None:
        if self.entry_direction == "up":
            if prev == "below" and curr == "above":
                return CrossingDirection.IN
            if prev == "above" and curr == "below":
                return CrossingDirection.OUT
        else:
            if prev == "above" and curr == "below":
                return CrossingDirection.IN
            if prev == "below" and curr == "above":
                return CrossingDirection.OUT
        return None

    def _is_eligible(self, track: Track) -> bool:
        conf = max(track.peak_confidence, track.confidence)
        return track.age >= self.min_track_age and conf >= self.min_confidence

    def _commit(self, pending: _PendingCrossing) -> CrossingEvent:
        cls = pending.class_name
        if pending.direction == CrossingDirection.IN:
            self.state.total_in[cls] = self.state.total_in.get(cls, 0) + 1
        else:
            self.state.total_out[cls] = self.state.total_out.get(cls, 0) + 1

        event = CrossingEvent(
            track_id=pending.track_id,
            class_name=cls,
            direction=pending.direction,
            confidence=pending.confidence,
        )
        self._recent_events.append({
            "track_id": pending.track_id,
            "class_name": cls,
            "direction": pending.direction.value,
            "confidence": round(pending.confidence, 2),
        })
        logger.info(
            "Gate %s: %s %s (#%s, conf=%.0f%%)",
            self.gate_id,
            pending.direction.value,
            cls,
            pending.track_id,
            pending.confidence * 100,
        )
        return event

    def _make_pending(self, track: Track, direction: CrossingDirection) -> _PendingCrossing:
        return _PendingCrossing(
            track_id=track.track_id,
            class_name=track.stable_class,
            direction=direction,
            confidence=max(track.peak_confidence, track.confidence),
        )

    def update(self, tracks: list[Track]) -> list[CrossingEvent]:
        events: list[CrossingEvent] = []
        active_ids = {t.track_id for t in tracks}
        line_a = (float(self.line[0]), float(self.line[1]))
        line_b = (float(self.line[2]), float(self.line[3]))

        for track in tracks:
            if track.crossed:
                continue
            # Kotak prediksi Kalman tidak dipakai untuk arah (sering terbalik / partikel).
            if getattr(track, "frames_since_seen", 0) > 0:
                continue

            cx, cy = self._counting_point(track)
            curr_side = self._point_side(cx, cy)
            prev_side = self._prev_side.get(track.track_id)
            prev_pt = self._prev_point.get(track.track_id)

            crossed_now = False
            if prev_side is not None and prev_side != curr_side:
                crossed_now = True
            elif prev_pt is not None and self._segments_intersect(prev_pt, (cx, cy), line_a, line_b):
                crossed_now = True
                if prev_side is None:
                    prev_side = "below" if curr_side == "above" else "above"

            if crossed_now and track.track_id not in self._pending:
                direction = self._resolve_direction(prev_pt, (cx, cy), prev_side, curr_side)
                if direction is not None and self._direction_allowed(direction, cx, cy):
                    self._pending[track.track_id] = self._make_pending(track, direction)

            self._prev_side[track.track_id] = curr_side
            self._prev_point[track.track_id] = (cx, cy)

            pending = self._pending.get(track.track_id)
            if pending is None:
                continue

            pending.class_name = track.stable_class
            pending.confidence = max(pending.confidence, track.peak_confidence, track.confidence)
            if prev_pt is not None:
                refined = self._resolve_direction(prev_pt, (cx, cy), prev_side, curr_side)
                if refined is not None:
                    pending.direction = refined

            if self._is_eligible(track):
                track.crossed = True
                events.append(self._commit(self._pending.pop(track.track_id)))

        stale = [tid for tid in self._prev_side if tid not in active_ids]
        for tid in stale:
            pending = self._pending.pop(tid, None)
            if pending is not None:
                events.append(self._commit(pending))
            self._prev_side.pop(tid, None)
            self._prev_point.pop(tid, None)

        return events
