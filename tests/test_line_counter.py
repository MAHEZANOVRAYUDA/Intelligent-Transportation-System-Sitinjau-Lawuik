"""Tes logika counting: pending crossing tidak boleh hilang meski umur/confidence belum cukup."""

from src.counting.line_counter import CrossingDirection, LineCounter
from src.detection.tracker import Track


def _track(tid: int, y: int, age: int, conf: float, cls: str = "mobil") -> Track:
    return Track(
        track_id=tid,
        class_name=cls,
        centroid=(100.0, float(y)),
        bbox=[80, y - 20, 120, y],
        confidence=conf,
        peak_confidence=conf,
        age=age,
        class_votes={cls: max(age, 1)},
    )


def _counter() -> LineCounter:
    # Garis horizontal y=100. Sisi "below" = y<100, "above" = y>=100.
    # entry_direction "up" → IN = below → above.
    return LineCounter(
        line=[0, 100, 200, 100],
        entry_direction="up",
        min_track_age=3,
        min_confidence=0.30,
        lane_divider=None,
    )


def test_pending_commit_when_age_reaches_minimum():
    counter = _counter()
    events = counter.update([_track(1, 80, age=1, conf=0.6)])
    assert events == []

    events = counter.update([_track(1, 120, age=2, conf=0.6)])
    assert events == []
    assert 1 in counter._pending

    events = counter.update([_track(1, 130, age=3, conf=0.6)])
    assert len(events) == 1
    assert events[0].direction == CrossingDirection.IN
    assert events[0].class_name == "mobil"
    assert counter.state.total_in["mobil"] == 1


def test_cross_then_disappear_still_saved():
    counter = _counter()
    counter.update([_track(7, 70, age=1, conf=0.55)])
    events = counter.update([_track(7, 140, age=2, conf=0.55)])
    assert events == []

    events = counter.update([])
    assert len(events) == 1
    assert events[0].direction == CrossingDirection.IN
    assert events[0].track_id == 7


def test_peak_confidence_allows_count_after_dip():
    counter = _counter()
    t1 = _track(3, 60, age=3, conf=0.45)
    counter.update([t1])

    t2 = _track(3, 150, age=4, conf=0.22)
    t2.peak_confidence = 0.45
    events = counter.update([t2])
    assert len(events) == 1
    assert events[0].direction == CrossingDirection.IN


def test_low_confidence_crossing_is_saved():
    counter = LineCounter(line=[0, 100, 200, 100], entry_direction="up")
    counter.update([_track(9, 70, age=1, conf=0.08)])
    events = counter.update([_track(9, 140, age=1, conf=0.08)])
    assert len(events) == 1
    assert events[0].direction == CrossingDirection.IN


def test_jump_across_line_still_counts():
    counter = LineCounter(line=[0, 100, 200, 100], entry_direction="up")
    counter.update([_track(4, 40, age=1, conf=0.4)])
    events = counter.update([_track(4, 190, age=2, conf=0.4)])
    assert len(events) == 1
    assert events[0].track_id == 4


def test_entry_down_toward_camera_is_out():
    counter = LineCounter(line=[0, 100, 200, 100], entry_direction="down")
    counter.update([_track(2, 50, age=1, conf=0.6)])
    events = counter.update([_track(2, 160, age=2, conf=0.6)])
    assert len(events) == 1
    assert events[0].direction == CrossingDirection.OUT


def test_entry_down_receding_is_in():
    counter = LineCounter(line=[0, 100, 200, 100], entry_direction="down")
    counter.update([_track(2, 160, age=1, conf=0.6)])
    events = counter.update([_track(2, 50, age=2, conf=0.6)])
    assert len(events) == 1
    assert events[0].direction == CrossingDirection.IN


def test_lane_overrides_motion_when_clearly_outbound():
    counter = LineCounter(
        line=[0, 100, 400, 100],
        entry_direction="up",
        lane_divider=[200, 0, 200, 200],
        inbound_side="left",
    )

    def box(tid: int, y: int) -> Track:
        x = 300
        return Track(
            track_id=tid,
            class_name="mobil",
            centroid=(float(x), float(y)),
            bbox=[x - 20, y - 20, x + 20, y],
            confidence=0.7,
            peak_confidence=0.7,
            age=2,
            class_votes={"mobil": 2},
        )

    counter.update([box(8, 70)])
    events = counter.update([box(8, 150)])
    assert len(events) == 1
    assert events[0].direction == CrossingDirection.OUT


def test_predicted_bbox_does_not_count():
    counter = LineCounter(line=[0, 100, 200, 100], entry_direction="up")
    counter.update([_track(5, 70, age=1, conf=0.5)])
    ghost = _track(5, 150, age=2, conf=0.5)
    ghost.frames_since_seen = 1
    events = counter.update([ghost])
    assert events == []
