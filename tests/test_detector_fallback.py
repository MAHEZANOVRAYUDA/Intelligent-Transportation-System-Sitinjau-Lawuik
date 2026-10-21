"""Unit test untuk HailoDetector status 74 error handling dan graceful fallback VehicleDetector."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest

from src.detection.hailo_detector import HailoDetector
from src.detection.detector import VehicleDetector


def test_hailo_detector_status_74_diagnostic():
    """Memverifikasi bahwa status 74 tidak mengaktifkan mock mode melainkan mencatat error diagnostik."""
    from src.config import ROOT_DIR
    detector = HailoDetector(hef_path=ROOT_DIR / "models" / "yolov8n.hef", mock_mode=False)

    # Simulasikan VDevice melempar error status 74
    with patch.dict("sys.modules", {"hailo_platform": MagicMock()}):
        import sys
        mock_hp = sys.modules["hailo_platform"]
        mock_hp.VDevice.side_effect = RuntimeError(
            "CHECK_SUCCESS failed with status=HAILO_OUT_OF_PHYSICAL_DEVICES(74)"
        )

        loaded = detector.load()
        assert loaded is False
        assert detector.is_loaded is False
        assert detector.is_mock is False
        assert detector.init_error is not None
        assert "74" in detector.init_error


def test_vehicle_detector_graceful_fallback():
    """Memverifikasi bahwa VehicleDetector otomatis fallback ke Ultralytics saat Hailo gagal."""
    vd = VehicleDetector(backend="hailo")

    # Mock HailoDetector agar load() mengembalikan False
    with patch("src.detection.detector.HailoDetector") as mock_hd_cls:
        mock_hd_instance = MagicMock()
        mock_hd_instance.load.return_value = False
        mock_hd_instance.is_mock = False
        mock_hd_instance.init_error = "status 74 device busy"
        mock_hd_cls.return_value = mock_hd_instance

        # Mock Ultralytics YOLO agar berhasil di-load
        with patch("ultralytics.YOLO") as mock_yolo:
            mock_model = MagicMock()
            mock_yolo.return_value = mock_model

            success = vd.load()
            assert success is True
            assert vd.is_loaded is True
            assert vd._model is not None


def test_hailo_detector_mps_strategy_success():
    """Memverifikasi bahwa jika direct mode gagal, strategi MPS berhasil memuat Hailo."""
    from src.config import ROOT_DIR
    detector = HailoDetector(hef_path=ROOT_DIR / "models" / "yolov8n.hef", mock_mode=False)

    with patch.dict("sys.modules", {"hailo_platform": MagicMock()}):
        import sys
        mock_hp = sys.modules["hailo_platform"]
        # Panggilan pertama (plain) & kedua (direct) gagal, panggilan ketiga (MPS) sukses
        mock_vdevice = MagicMock()
        mock_network_group = MagicMock()
        mock_vdevice.configure.return_value = [mock_network_group]
        mock_hp.VDevice.side_effect = [
            RuntimeError("status=74 plain busy"),
            RuntimeError("status=74 direct busy"),
            mock_vdevice,
        ]

        loaded = detector.load()
        assert loaded is True
        assert detector.is_loaded is True
        assert detector.is_mock is False
        assert detector._vdevice is mock_vdevice
