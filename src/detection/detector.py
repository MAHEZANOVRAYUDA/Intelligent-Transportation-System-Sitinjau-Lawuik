"""YOLOv8 vehicle detector."""

from __future__ import annotations

import logging

import numpy as np

from src.config import ROOT_DIR, get_coco_to_local_map, get_detection_config

logger = logging.getLogger(__name__)


class VehicleDetector:
    """Wrapper YOLOv8 untuk deteksi kendaraan."""

    COCO_VEHICLE_IDS = {2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}
    COCO_TWO_WHEEL_IDS = {1: "bicycle", 3: "motorcycle"}
    COCO_PERSON_ID = 0

    def __init__(self):
        self._cfg = get_detection_config()
        self._coco_map = get_coco_to_local_map()
        self._model = None
        self._loaded = False

    def load(self) -> bool:
        try:
            from ultralytics import YOLO

            model_path = ROOT_DIR / self._cfg.model_path
            if not model_path.exists():
                logger.info("Model belum ada, mengunduh YOLOv8n...")
                model_path.parent.mkdir(parents=True, exist_ok=True)
                self._model = YOLO("yolov8n.pt")
                self._model.save(str(model_path))
            else:
                self._model = YOLO(str(model_path))

            self._loaded = True
            logger.info("Model YOLO loaded: %s", model_path)
            return True
        except Exception as e:
            logger.error("Gagal load model YOLO: %s", e)
            return False

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    @staticmethod
    def _iou(a: list[int], b: list[int]) -> float:
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

    def _person_looks_like_rider(self, bbox: list[int], frame_h: int, frame_w: int) -> bool:
        """
        Di ruas Sitinjau Laut, orang di badan jalan hampir selalu pengendara motor.
        Filter ini menolak penumpang di dalam mobil dan objek kecil di langit.
        """
        x1, y1, x2, y2 = bbox
        w = max(1, x2 - x1)
        h = max(1, y2 - y1)
        cy = (y1 + y2) / 2.0
        if cy < frame_h * 0.32:
            return False
        if h < frame_h * 0.035 or h > frame_h * 0.50:
            return False
        if w < frame_w * 0.012 or w > frame_w * 0.28:
            return False
        if w / h > 1.8:
            return False
        return True

    def detect(self, frame: np.ndarray) -> list[dict]:
        """
        Deteksi kendaraan dalam frame.

        Returns:
            List of {bbox: [x1,y1,x2,y2], confidence, class_name, class_coco}
        """
        if not self._loaded or self._model is None:
            return []

        # Jangan filter kelas di YOLO: NMS sering menyimpan 'person' dan membuang 'motorcycle'.
        results = self._model.predict(
            frame,
            conf=self._cfg.confidence,
            iou=self._cfg.iou,
            imgsz=self._cfg.imgsz,
            device=self._cfg.device,
            classes=[0, 1, 2, 3, 5, 7],
            verbose=False,
        )

        frame_h, frame_w = frame.shape[:2]
        vehicles: list[dict] = []
        persons: list[dict] = []

        for result in results:
            if result.boxes is None:
                continue
            for box in result.boxes:
                cls_id = int(box.cls[0])
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                bbox = [int(x1), int(y1), int(x2), int(y2)]
                conf = float(box.conf[0])
                item = {"bbox": bbox, "confidence": conf, "cls_id": cls_id}

                if cls_id == self.COCO_PERSON_ID:
                    persons.append(item)
                    continue

                if cls_id in self.COCO_TWO_WHEEL_IDS:
                    coco_name = self.COCO_TWO_WHEEL_IDS[cls_id]
                    local_name = self._coco_map.get("motorcycle") or self._coco_map.get(coco_name)
                    if local_name is None:
                        continue
                    vehicles.append(
                        {
                            "bbox": bbox,
                            "confidence": conf,
                            "class_coco": coco_name,
                            "class_name": local_name,
                        }
                    )
                    continue

                if cls_id not in self.COCO_VEHICLE_IDS:
                    continue
                coco_name = self.COCO_VEHICLE_IDS[cls_id]
                local_name = self._coco_map.get(coco_name)
                if local_name is None:
                    continue
                vehicles.append(
                    {
                        "bbox": bbox,
                        "confidence": conf,
                        "class_coco": coco_name,
                        "class_name": local_name,
                    }
                )

        large_vehicles = [v for v in vehicles if v["class_name"] in ("mobil", "bus", "truck")]
        for person in persons:
            if not self._person_looks_like_rider(person["bbox"], frame_h, frame_w):
                continue
            if any(self._iou(person["bbox"], v["bbox"]) > 0.18 for v in large_vehicles):
                continue
            if any(self._iou(person["bbox"], v["bbox"]) > 0.25 for v in vehicles if v["class_name"] == "motor"):
                continue
            vehicles.append(
                {
                    "bbox": person["bbox"],
                    "confidence": person["confidence"],
                    "class_coco": "person",
                    "class_name": "motor",
                }
            )

        return vehicles
