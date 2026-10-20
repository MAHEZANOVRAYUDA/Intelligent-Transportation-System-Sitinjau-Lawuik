"""Unit test untuk mekanisme frame skip dan visual overlay holding.

Menguji kepatuhan terhadap solusi:
1. Tidak ada panggilan tracker.update([]) pada frame skip.
2. Tidak ada kotak berkedip (overlay tetap memiliki track yang ditahan).
3. Tidak ada kotak dobel karena miss semu.
4. Prediksi Kalman murni (unconfirmed) tidak ikut digambar (mencegah melayang).
"""

import copy
import numpy as np
from src.detection.tracker import SimpleTracker, Track


def test_frame_skip_prevents_duplicate_and_drift():
    """Memverifikasi bahwa tidak memanggil tracker.update([]) di frame skip mempertahankan ID objek."""
    tracker = SimpleTracker(
        max_disappeared=30,
        max_distance=280,
        min_hits=1,
        association="quadratic",
        lambda_consistency=5.0,
    )

    # Frame 1: YOLO mendeteksi mobil
    det_frame1 = [{"bbox": [100, 100, 160, 180], "confidence": 0.85, "class_name": "mobil"}]
    tracks_f1 = tracker.update(det_frame1)
    assert len(tracks_f1) == 1
    tid_initial = tracks_f1[0].track_id
    assert tracks_f1[0].frames_since_seen == 0

    # Simpan stable tracks untuk ditahan
    held_tracks = [
        copy.deepcopy(t) for t in tracks_f1
        if t.age >= 1 and getattr(t, "frames_since_seen", 0) == 0
    ]

    # Frame 2 (Skip Frame):
    # Sesuai solusi: tracker.update([]) TIDAK DIPANGGIL!
    # Status track di tracker tetap intak (frames_since_seen tetap 0).
    assert tracker.tracks[tid_initial].frames_since_seen == 0

    # Overlay di frame skip memakai held_tracks:
    # Bounding box tetap ada (tidak berkedip/hilang)
    overlay_tracks = [
        t for t in held_tracks
        if t.age >= 1 and getattr(t, "frames_since_seen", 0) == 0
    ]
    assert len(overlay_tracks) == 1
    assert overlay_tracks[0].track_id == tid_initial
    assert overlay_tracks[0].bbox == [100, 100, 160, 180]

    # Frame 3: YOLO jalan lagi dengan perpindahan wajar
    det_frame3 = [{"bbox": [106, 104, 166, 184], "confidence": 0.82, "class_name": "mobil"}]
    tracks_f3 = tracker.update(det_frame3)

    # Memastikan ID sama (TIDAK DOBEL)
    assert len(tracks_f3) == 1
    assert tracks_f3[0].track_id == tid_initial
    assert len(tracker.tracks) == 1  # Hanya ada 1 track di memori tracker


def test_kalman_prediction_is_excluded_from_overlay():
    """Memverifikasi bahwa kotak prediksi Kalman yang unconfirmed tidak masuk overlay."""
    tracker = SimpleTracker(
        max_disappeared=5,
        min_hits=1,
        association="quadratic",
    )

    det = [{"bbox": [100, 100, 160, 180], "confidence": 0.8, "class_name": "mobil"}]
    tracker.update(det)

    # Deteksi hilang di YOLO frame berikutnya
    tracks_after_miss = tracker.update([])

    # Kalman filter memprediksi koordinat
    assert len(tracks_after_miss) == 1
    assert tracks_after_miss[0].frames_since_seen == 1

    # Filter overlay hanya mengizinkan frames_since_seen == 0
    overlay_visible = [
        t for t in tracks_after_miss
        if t.age >= 1 and getattr(t, "frames_since_seen", 0) == 0
    ]

    # Hasil: Kotak Kalman yang melayang TIDAK ditampilkan di overlay!
    assert len(overlay_visible) == 0


def test_empty_yolo_detection_clears_held_tracks():
    """Memverifikasi jika tidak ada deteksi pada frame YOLO, track yang ditahan ikut bersih."""
    tracker = SimpleTracker(min_hits=1)
    det = [{"bbox": [100, 100, 160, 180], "confidence": 0.8, "class_name": "mobil"}]
    tracks = tracker.update(det)

    held_tracks = [
        copy.deepcopy(t) for t in tracks
        if t.age >= 1 and getattr(t, "frames_since_seen", 0) == 0
    ]
    assert len(held_tracks) == 1

    # Kendaraan keluar total dari kamera, YOLO mengembalikan []
    empty_tracks = tracker.update([])
    new_held_tracks = [
        copy.deepcopy(t) for t in empty_tracks
        if t.age >= 1 and getattr(t, "frames_since_seen", 0) == 0
    ]

    # new_held_tracks harus kosong, tidak ada kotak hantu tersisa
    assert len(new_held_tracks) == 0


def test_detection_worker_state_handling():
    """Memverifikasi inisialisasi dan pembersihan state _last_stable_tracks di DetectionWorker."""
    from src.worker.detection_worker import DetectionWorker
    from src.capture.stream_manager import StreamRegistry
    from src.analytics.density import RoadOccupancyManager

    registry = StreamRegistry()
    occupancy = RoadOccupancyManager()
    worker = DetectionWorker(registry, occupancy)

    assert worker._last_stable_tracks == {}
    assert worker._last_detections == {}

    # Simulasi pengisian state
    worker._last_detections["A"] = [{"bbox": [1, 2, 3, 4]}]
    worker._last_stable_tracks["A"] = ["dummy_track"]

    # Panggil reset_runtime
    worker.reset_runtime()
    assert worker._last_detections == {}
    assert worker._last_stable_tracks == {}

