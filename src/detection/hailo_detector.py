"""Hailo-8L NPU vehicle detector implementation."""

from __future__ import annotations

import logging
import pathlib
from typing import Any
import numpy as np

from src.config import ROOT_DIR, get_coco_to_local_map, get_detection_config
from src.detection.base import BaseDetector, calculate_iou, deduplicate_boxes

logger = logging.getLogger(__name__)


class HailoDetector(BaseDetector):
    """
    Detektor kendaraan terakselerasi hardware NPU Hailo-8L (Raspberry Pi AI Kit).
    
    Mendukung runtime native via `pyhailort` pada Raspberry Pi OS,
    serta mode simulasi aman saat dijalankan di workstation laptop tanpa chip fisik.
    """

    def __init__(self, hef_path: str | pathlib.Path | None = None, mock_mode: bool = False):
        self._cfg = get_detection_config()
        self._coco_map = get_coco_to_local_map()
        self._mock_mode = mock_mode

        if hef_path is None:
            self.hef_path = ROOT_DIR / "models" / "yolov8n.hef"
        else:
            self.hef_path = pathlib.Path(hef_path)

        self._loaded = False
        self._vdevice: Any = None
        self._target: Any = None
        self._infer_model: Any = None
        self._configured_infer_model: Any = None

    def load(self) -> bool:
        """Memuat runtime Hailo-8L dan file biner HEF."""
        if not self.hef_path.exists():
            logger.warning("File HEF Hailo tidak ditemukan di %s. Mencoba fallback ke download...", self.hef_path)
            try:
                from scripts.download_hailo_model import download_model
                download_model("yolov8n", output_dir=self.hef_path.parent)
            except Exception as e:
                logger.error("Gagal mendownload model Hailo otomatis: %s", e)

        try:
            # Mencoba import Hailo Runtime API (hanya ada jika hailo-all terpasang di Raspberry Pi)
            from hailo_platform import (  # type: ignore
                ConfigureParams,
                Device,
                FormatType,
                HailoSchedulingAlgorithm,
                HailoStreamInterface,
                HEF,
                InferVStreams,
                InputVStreamParams,
                OutputVStreamParams,
                VDevice,
            )

            logger.info("Menginisialisasi Hailo VDevice untuk arsitektur Hailo-8L...")
            
            vdevice = None
            init_errors = []

            # Strategi 1: Direct Physical Allocation
            try:
                params = VDevice.create_params()
                vdevice = VDevice(params)
                logger.info("Hailo VDevice berhasil diinisialisasi via Direct Physical Mode.")
            except Exception as e_direct:
                init_errors.append(f"Direct: {e_direct}")
                logger.warning("Direct physical allocation gagal (%s). Mencoba Multi-Process Service (MPS)...", e_direct)

                # Strategi 2: Multi-Process Service (MPS) Mode (jika hailort.service aktif di Raspberry Pi OS)
                try:
                    params_mps = VDevice.create_params()
                    params_mps.scheduling_algorithm = HailoSchedulingAlgorithm.ROUND_ROBIN
                    params_mps.group_id = "SHARED"
                    params_mps.multi_process_service = True
                    vdevice = VDevice(params_mps)
                    logger.info("Hailo VDevice berhasil diinisialisasi via Multi-Process Service (MPS)!")
                except Exception as e_mps:
                    init_errors.append(f"MPS: {e_mps}")
                    logger.warning("MPS mode gagal (%s). Mencoba Explicit Scan Device IDs...", e_mps)

                    # Strategi 3: Explicit Scan Device IDs
                    try:
                        scan_devices = Device.scan()
                        if scan_devices:
                            params_scan = VDevice.create_params()
                            params_scan.device_ids = scan_devices
                            vdevice = VDevice(params_scan)
                            logger.info("Hailo VDevice berhasil diinisialisasi via explicit device ID: %s", scan_devices)
                        else:
                            raise RuntimeError("Device.scan() tidak menemukan device fisik aktif.")
                    except Exception as e_scan:
                        init_errors.append(f"Device Scan: {e_scan}")
                        logger.error("Seluruh 3 strategi alokasi Hailo VDevice gagal: %s", " | ".join(init_errors))
                        raise e_direct

            self._vdevice = vdevice
            self._hef = HEF(str(self.hef_path))

            # Konfigurasi stream inferensi
            configure_params = ConfigureParams.create_from_hef(
                hef=self._hef, interface=HailoStreamInterface.PCIe
            )
            self._network_group = self._vdevice.configure(self._hef, configure_params)[0]
            self._network_group_params = self._network_group.create_params()

            self._input_vstream_params = InputVStreamParams.make(
                self._network_group, format_type=FormatType.UINT8
            )
            self._output_vstream_params = OutputVStreamParams.make(
                self._network_group, format_type=FormatType.FLOAT32
            )

            self._loaded = True
            self.init_error = None
            logger.info("Hailo-8L NPU berhasil dimuat dari %s!", self.hef_path)
            return True

        except ImportError:
            self.init_error = "Driver 'hailo_platform' (pyhailort) tidak terpasang"
            if self._mock_mode:
                logger.warning(
                    "Driver 'hailo_platform' tidak ditemukan. Menjalankan HailoDetector dalam mode mock simulasi."
                )
                self._loaded = True
                return True
            else:
                logger.info(
                    "Driver 'hailo_platform' (pyhailort) tidak ditemukan di environment ini."
                )
                self._loaded = False
                return False
        except Exception as e:
            err_msg = str(e)
            self.init_error = err_msg
            self._loaded = False
            self._mock_mode = False
            if "74" in err_msg or "HAILO_OUT_OF_PHYSICAL_DEVICES" in err_msg or "not enough free devices" in err_msg:
                logger.error(
                    "Gagal inisialisasi Hailo NPU: Chip Hailo-8L sedang sibuk atau terkunci oleh proses lain (status 74: HAILO_OUT_OF_PHYSICAL_DEVICES).\n"
                    "  [PANDUAN TROUBLESHOOTING RASPBERRY PI]:\n"
                    "  1. Cek layanan background Multi-Process Service (hailort.service):\n"
                    "       sudo systemctl stop hailort.service\n"
                    "     atau aktifkan ulang:\n"
                    "       sudo systemctl restart hailort.service\n"
                    "  2. Periksa dan bunuh proses python/zombie yang mengunci chip NPU:\n"
                    "       sudo fuser -v /dev/hailo0\n"
                    "       sudo fuser -k /dev/hailo0\n"
                    "  3. Pastikan izin akses file device (permissions):\n"
                    "       sudo chmod 666 /dev/hailo0\n"
                    "  4. Periksa status fisik via Hailo CLI:\n"
                    "       hailortcli scan"
                )
            else:
                logger.error("Gagal inisialisasi Hailo NPU: %s", e)
            return False

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    @property
    def is_mock(self) -> bool:
        return self._mock_mode

    def detect(self, frame: np.ndarray) -> list[dict]:
        """
        Menjalankan inferensi pada NPU Hailo-8L dan mengembalikan deteksi berstandar.
        """
        if not self._loaded:
            return []

        frame_h, frame_w = frame.shape[:2]

        if self._mock_mode:
            # Return safe empty or minimal structure in mock mode
            return []

        try:
            import cv2
            from hailo_platform import InferVStreams  # type: ignore

            # Preprocessing: resize ke 640x640 sesuai bentuk input model
            input_frame = cv2.resize(frame, (640, 640))
            input_frame = np.expand_dims(input_frame, axis=0)

            # Eksekusi inferensi via PCIe NPU stream
            with InferVStreams(
                self._network_group,
                self._input_vstream_params,
                self._output_vstream_params,
            ) as infer_pipeline:
                input_data = {self._hef.get_input_vstream_infos()[0].name: input_frame}
                with self._network_group.activate(self._network_group_params):
                    raw_outputs = infer_pipeline.infer(input_data)

            # Post-processing output Hailo YOLOv8
            return self._parse_hailo_output(raw_outputs, frame_w, frame_h)

        except Exception as e:
            logger.error("Error saat inferensi Hailo NPU: %s", e)
            return []

    def _parse_hailo_output(self, raw_outputs: dict, orig_w: int, orig_h: int) -> list[dict]:
        """Mengekstrak bounding box, skor, dan kelas dari output tensor Hailo."""
        detections: list[dict] = []
        
        # Format keluaran YOLOv8 pada Hailo NPU NMS post-process
        # Tensor biasanya berbentuk [num_detections, [ymin, xmin, ymax, xmax, score, class]]
        for stream_name, tensor in raw_outputs.items():
            if not isinstance(tensor, np.ndarray):
                continue
            
            data = np.squeeze(tensor)
            if data.ndim != 2 or data.shape[1] < 6:
                continue

            for row in data:
                ymin, xmin, ymax, xmax, score, cls_id = row[:6]
                cls_id = int(cls_id)
                score = float(score)

                if score < self._cfg.confidence:
                    continue

                if cls_id not in self.COCO_VEHICLE_IDS and cls_id not in self.COCO_TWO_WHEEL_IDS:
                    continue

                # Skala kembali ke resolusi asli
                x1 = int(xmin * orig_w)
                y1 = int(ymin * orig_h)
                x2 = int(xmax * orig_w)
                y2 = int(ymax * orig_h)

                bbox = [max(0, x1), max(0, y1), min(orig_w, x2), min(orig_h, y2)]
                
                # Pemetaan kelas ke nama lokal (mobil, motor, bus, truk)
                if cls_id in self.COCO_TWO_WHEEL_IDS:
                    coco_name = "motorcycle"
                else:
                    coco_name = self.COCO_VEHICLE_IDS.get(cls_id, "car")
                    
                local_name = self._coco_map.get(coco_name, coco_name)

                detections.append({
                    "bbox": bbox,
                    "confidence": score,
                    "class_coco": coco_name,
                    "class_name": local_name,
                })

        return deduplicate_boxes(detections)

    def close(self) -> None:
        """Melepaskan resource Hailo VDevice agar file descriptor fisik PCIe tidak terkunci."""
        try:
            if hasattr(self, "_vdevice") and self._vdevice is not None:
                if hasattr(self._vdevice, "release"):
                    self._vdevice.release()
                self._vdevice = None
        except Exception:
            pass
        self._loaded = False

    def __del__(self) -> None:
        self.close()
