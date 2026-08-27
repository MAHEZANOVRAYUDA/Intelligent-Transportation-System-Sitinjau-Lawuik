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
