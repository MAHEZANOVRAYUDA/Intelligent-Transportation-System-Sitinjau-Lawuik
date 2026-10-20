"""Tes filter kotak noise / partikel yang salah jadi motor."""

from src.detection.detector import VehicleDetector


def test_tiny_box_rejected_as_motor():
    assert not VehicleDetector._box_large_enough([10, 10, 22, 24], 1296, 2304, kind="motor")


def test_real_motor_box_accepted():
    # ~80x140 di frame 2304x1296
    assert VehicleDetector._box_large_enough([200, 600, 280, 740], 1296, 2304, kind="motor")


def test_person_speck_not_rider():
    det = VehicleDetector.__new__(VehicleDetector)
    speck = [100, 800, 118, 822]
    assert not det._person_looks_like_rider(speck, 1296, 2304, 0.20)
    assert not det._person_looks_like_rider(speck, 1296, 2304, 0.90)
