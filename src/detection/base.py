"""Abstract Base Detector and Common Geometric Helpers."""

from __future__ import annotations

from abc import ABC, abstractmethod
import logging
import numpy as np

logger = logging.getLogger(__name__)


def calculate_iou(a: list[int], b: list[int]) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    area_a = max(0, ax2 - ax1) * max(0, ay2 - ay1)
    area_b = max(0, bx2 - bx1) * max(0, by2 - by1)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def deduplicate_boxes(vehicles: list[dict], iou_threshold: float = 0.55) -> list[dict]:
    """Menghilangkan duplikasi box jika tumpang tindih tinggi untuk objek fisik yang sama."""
    if len(vehicles) < 2:
        return vehicles
    keep = [True] * len(vehicles)
    for i in range(len(vehicles)):
        if not keep[i]:
            continue
        for j in range(i + 1, len(vehicles)):
            if not keep[j]:
                continue
            overlap = calculate_iou(vehicles[i]["bbox"], vehicles[j]["bbox"])
            if overlap < iou_threshold:
                continue
            if vehicles[i]["confidence"] >= vehicles[j]["confidence"]:
                keep[j] = False
            else:
                keep[i] = False
                break
    return [v for v, ok in zip(vehicles, keep) if ok]


class BaseDetector(ABC):
    """Antarmuka dasar untuk semua backend detektor kendaraan."""

    COCO_VEHICLE_IDS = {2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}
    COCO_TWO_WHEEL_IDS = {1: "bicycle", 3: "motorcycle"}
    COCO_PERSON_ID = 0

    @abstractmethod
    def load(self) -> bool:
        """Memuat bobot model atau runtime NPU."""
        pass

    @property
    @abstractmethod
    def is_loaded(self) -> bool:
        """Status apakah model telah siap digunakan."""
        pass

    @abstractmethod
    def detect(self, frame: np.ndarray) -> list[dict]:
        """
        Melakukan inferensi deteksi kendaraan pada frame citra.

        Returns:
            List of dict: [{
                'bbox': [x1, y1, x2, y2],
                'confidence': float,
                'class_name': str,
                'class_coco': str
            }]
        """
        pass
