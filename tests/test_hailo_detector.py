"""Unit tests untuk pengujian parser polimorfik output Hailo-8L NPU."""

from __future__ import annotations

import numpy as np
import pytest

from src.detection.hailo_detector import HailoDetector


def test_hailo_parse_official_list_format():
    """Menguji parsing format resmi HailoRT NMS (list 80 array kelas)."""
    detector = HailoDetector(mock_mode=True)
    orig_w, orig_h = 1920, 1080

    # Buat list 80 kelas COCO kosong
    raw_outputs = [[] for _ in range(80)]

    # Kelas 2 (car) dengan 1 mobil: [ymin, xmin, ymax, xmax, score] (skala 0.0 - 1.0)
    raw_outputs[2] = np.array([
        [0.2, 0.3, 0.6, 0.7, 0.88]
    ], dtype=np.float32)

    # Kelas 3 (motorcycle) dengan 1 motor
    raw_outputs[3] = np.array([
        [0.4, 0.1, 0.8, 0.25, 0.75]
    ], dtype=np.float32)

    # Kelas 0 (person) - harus diabaikan jika bukan kendaraan
    raw_outputs[0] = np.array([
        [0.5, 0.5, 0.7, 0.6, 0.90]
    ], dtype=np.float32)

    dets = detector._parse_hailo_output({"yolov8_nms_postprocess": raw_outputs}, orig_w, orig_h)

    assert len(dets) == 2
    classes = {d["class_name"] for d in dets}
    assert "mobil" in classes
    assert "motor" in classes

    car = next(d for d in dets if d["class_name"] == "mobil")
    assert car["confidence"] == pytest.approx(0.88, abs=1e-3)
    # Bounding box harus diskalakan ke dimensi citra
    assert car["bbox"] == [int(0.3 * 1920), int(0.2 * 1080), int(0.7 * 1920), int(0.6 * 1080)]


def test_hailo_parse_matrix_2d_format():
    """Menguji format alternatif matriks 2D (N, 6) [ymin, xmin, ymax, xmax, score, cls_id]."""
    detector = HailoDetector(mock_mode=True)
    orig_w, orig_h = 1280, 720

    tensor = np.array([
        [0.1, 0.2, 0.4, 0.5, 0.92, 2.0],  # Car (cls 2)
        [0.3, 0.4, 0.7, 0.8, 0.85, 7.0],  # Truck (cls 7)
        [0.5, 0.5, 0.6, 0.6, 0.10, 2.0],  # Low confidence car (< 0.25) -> filtered
    ], dtype=np.float32)

    dets = detector._parse_hailo_output({"output": tensor}, orig_w, orig_h)
    assert len(dets) == 2
    classes = {d["class_name"] for d in dets}
    assert "mobil" in classes
    assert "truck" in classes


def test_hailo_parse_3d_array_format():
    """Menguji format array 3D (80, N, 5)."""
    detector = HailoDetector(mock_mode=True)
    orig_w, orig_h = 1000, 1000

    arr = np.zeros((80, 1, 5), dtype=np.float32)
    # Bus (cls 5)
    arr[5, 0] = [0.1, 0.1, 0.5, 0.5, 0.80]

    dets = detector._parse_hailo_output({"stream": arr}, orig_w, orig_h)
    assert len(dets) == 1
    assert dets[0]["class_name"] == "bus"
    assert dets[0]["bbox"] == [100, 100, 500, 500]


def test_hailo_parse_empty_or_malformed():
    """Menguji ketahanan parser saat menerima output kosong atau invalid."""
    detector = HailoDetector(mock_mode=True)
    assert detector._parse_hailo_output({}, 1920, 1080) == []
    assert detector._parse_hailo_output(None, 1920, 1080) == []
    assert detector._parse_hailo_output({"out": []}, 1920, 1080) == []
