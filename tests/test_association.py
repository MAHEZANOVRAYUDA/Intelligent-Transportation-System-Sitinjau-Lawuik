"""Tes rumus asosiasi D / D* / D** dan persistensi track saat deteksi hilang."""

from src.detection.tracker import AssociationTracker, association_cost, iou


def test_penalty_table_matches_document():
    lam = 1.0
    expected = {
        0.0: (1.00, 1.00),
        0.2: (0.80, 0.64),
        0.4: (0.60, 0.36),
        0.5: (0.50, 0.25),
        0.6: (0.40, 0.16),
        0.8: (0.20, 0.04),
        1.0: (0.00, 0.00),
    }
    for t_ij, (lin, quad) in expected.items():
        d_star = association_cost(0.0, t_ij, formula="linear", lambda_consistency=lam)
        d_star2 = association_cost(0.0, t_ij, formula="quadratic", lambda_consistency=lam)
        assert abs(d_star - lin) < 1e-9
        assert abs(d_star2 - quad) < 1e-9


def test_quadratic_more_tolerant_when_iou_high():
    assert association_cost(1.0, 0.8, formula="quadratic", lambda_consistency=1.0) < association_cost(
        1.0, 0.8, formula="linear", lambda_consistency=1.0
    )


def test_track_survives_missed_detection():
    tracker = AssociationTracker(max_disappeared=5, association="quadratic", lambda_consistency=5.0)
    det = {"bbox": [100, 100, 160, 180], "confidence": 0.7, "class_name": "motor"}
    tracks = tracker.update([det])
    tid = tracks[0].track_id
    empty = tracker.update([])
    assert any(t.track_id == tid for t in empty)
    assert empty[0].frames_since_seen == 1


def test_same_object_keeps_id():
    tracker = AssociationTracker(association="quadratic")
    a = {"bbox": [100, 100, 160, 180], "confidence": 0.8, "class_name": "mobil"}
    b = {"bbox": [108, 104, 168, 184], "confidence": 0.75, "class_name": "mobil"}
    t0 = tracker.update([a])[0].track_id
    t1 = tracker.update([b])[0].track_id
    assert t0 == t1


def test_iou_identical_boxes():
    box = [10, 10, 50, 50]
    assert abs(iou(box, box) - 1.0) < 1e-9


def test_id_survives_class_switch_high_iou():
    tracker = AssociationTracker(association="quadratic")
    a = {"bbox": [100, 100, 180, 180], "confidence": 0.6, "class_name": "mobil"}
    b = {"bbox": [104, 102, 184, 184], "confidence": 0.5, "class_name": "truck"}
    t0 = tracker.update([a])[0].track_id
    t1 = tracker.update([b])[0].track_id
    assert t0 == t1
