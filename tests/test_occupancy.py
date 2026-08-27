"""Tes occupancy koridor: masuk menambah, keluar mengurangi."""

from src.analytics.density import RoadOccupancyManager


def test_enter_then_exit_updates_on_road():
    occ = RoadOccupancyManager()
    occ.set_dual_gate_mode(True)
    for _ in range(5):
        occ.register_entry("mobil", gate="A")
    assert occ.snapshot_to_dict()["on_road"]["mobil"] == 5

    occ.register_exit("mobil", gate="A")
    snap = occ.snapshot_to_dict()
    assert snap["on_road"]["mobil"] == 4
    assert snap["on_road_total"] == 4


def test_reset_clears_corridor():
    occ = RoadOccupancyManager()
    occ.set_dual_gate_mode(True)
    occ.register_entry("motor", gate="A")
    occ.reset()
    snap = occ.snapshot_to_dict()
    assert snap["on_road_total"] == 0
    assert snap["on_road"]["motor"] == 0
