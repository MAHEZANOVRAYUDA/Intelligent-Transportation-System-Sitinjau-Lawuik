"""Unit test untuk persistensi database dan in-memory cache hari ini."""

import pytest
from src.storage.database import (
    clear_all_records,
    get_today_crossings,
    invalidate_today_cache,
    save_crossing,
    save_snapshot,
    get_recent_snapshots,
)


def test_today_crossings_in_memory_cache():
    """Memverifikasi bahwa simpan crossing memperbarui cache in-memory secara instan."""
    clear_all_records()

    initial = get_today_crossings()
    assert initial["total_in"] == 0
    assert initial["total_out"] == 0

    # Simpan perlintasan masuk (IN) mobil & truk
    save_crossing(gate_id="A", direction="in", class_name="mobil", confidence=0.85, track_id=101)
    save_crossing(gate_id="A", direction="in", class_name="truck", confidence=0.92, track_id=102)

    # Simpan perlintasan keluar (OUT) motor
    save_crossing(gate_id="B", direction="out", class_name="motor", confidence=0.78, track_id=103)

    cached = get_today_crossings()
    assert cached["total_in"] == 2
    assert cached["total_out"] == 1
    assert cached["in"]["mobil"] == 1
    assert cached["in"]["truck"] == 1
    assert cached["out"]["motor"] == 1
    assert cached["by_class"]["mobil"] == 1
    assert cached["by_class"]["motor"] == 1


def test_clear_all_records_invalidates_cache():
    """Memverifikasi bahwa reset database mengosongkan kembali in-memory cache."""
    save_crossing(gate_id="A", direction="in", class_name="mobil", confidence=0.80)
    assert get_today_crossings()["total_in"] >= 1

    deleted = clear_all_records()
    assert deleted["vehicle_crossings"] >= 1

    fresh = get_today_crossings()
    assert fresh["total_in"] == 0
    assert fresh["total_out"] == 0
    assert fresh["in"]["mobil"] == 0


def test_snapshot_record_datetime_warning_free():
    """Memverifikasi penyimpanan snapshot berjalan mulus tanpa deprecation warning."""
    snap_data = {
        "on_road": {"motor": 2, "mobil": 5, "bus": 1, "truck": 3},
        "volume_used_meter_lajur": 150.0,
        "utilization_percent": 0.45,
        "status": "lancar",
    }
    save_snapshot(snap_data)
    recent = get_recent_snapshots(limit=5)
    assert len(recent) >= 1
    assert recent[-1]["status"] == "lancar"
    assert recent[-1]["on_road"]["mobil"] == 5
