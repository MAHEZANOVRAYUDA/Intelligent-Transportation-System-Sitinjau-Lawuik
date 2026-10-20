"""Tracker kendaraan: Kalman + asosiasi Mahalanobis dan term konsistensi IoU.

Rumus (dokumen penelitian Sitinjau Laut):
  D_ij   = (d_j - y_i)^T S_i^{-1} (d_j - y_i)          # Mahalanobis DeepSORT/SORT
  D*_ij  = D_ij + λ(1 - T_ij)                            # linear
  D**_ij = D_ij + λ(1 - T_ij)^2                          # kuadrat (arahan dosen)
  T_ij   = IoU(B_j^t, B_i^{t-1})
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np

logger = logging.getLogger(__name__)

CHI2_GATING_4D = 9.4877


@dataclass
class Track:
    track_id: int
    class_name: str
    centroid: tuple[float, float]
    bbox: list[int]
    confidence: float
    peak_confidence: float = 0.0
    frames_since_seen: int = 0
    crossed: bool = False
    age: int = 0
    class_votes: dict[str, float] = field(default_factory=dict)
    hits: int = 1
    prev_bbox: list[int] | None = None

    @property
    def stable_class(self) -> str:
        if not self.class_votes:
            return self.class_name
        return max(self.class_votes, key=self.class_votes.get)

    def vote_class(self, class_name: str, weight: float = 1.0) -> None:
        self.class_votes[class_name] = self.class_votes.get(class_name, 0) + max(0.05, weight)
        self.class_name = self.stable_class


def bbox_to_z(bbox: list[int]) -> np.ndarray:
    x1, y1, x2, y2 = [float(v) for v in bbox]
    w = max(1.0, x2 - x1)
    h = max(1.0, y2 - y1)
    cx = x1 + w / 2.0
    cy = y1 + h / 2.0
    s = w * h
    r = w / h
    return np.array([cx, cy, s, r], dtype=np.float64)


def z_to_bbox(z: np.ndarray) -> list[int]:
    cx, cy, s, r = [float(v) for v in z[:4]]
    s = max(s, 1.0)
    r = max(r, 0.05)
    w = float(np.sqrt(s * r))
    h = s / max(w, 1.0)
    x1 = int(round(cx - w / 2.0))
    y1 = int(round(cy - h / 2.0))
    x2 = int(round(cx + w / 2.0))
    y2 = int(round(cy + h / 2.0))
    return [x1, y1, x2, y2]


def iou(a: list[int], b: list[int]) -> float:
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
    return float(inter / union) if union > 0 else 0.0


def association_cost(
    mahalanobis: float,
    box_iou: float,
    *,
    formula: str,
    lambda_consistency: float,
) -> float:
    """D, D*, atau D** sesuai dokumen."""
    t = max(0.0, min(1.0, box_iou))
    gap = 1.0 - t
    if formula == "mahalanobis":
        return mahalanobis
    if formula == "linear":
        return mahalanobis + lambda_consistency * gap
    return mahalanobis + lambda_consistency * (gap ** 2)


class KalmanBoxFilter:
    """Filter Kalman 7D gaya SORT: [cx, cy, s, r, vx, vy, vs]."""

    def __init__(self, bbox: list[int]):
        z = bbox_to_z(bbox)
        self.x = np.zeros((7, 1), dtype=np.float64)
        self.x[:4, 0] = z
        self.F = np.eye(7, dtype=np.float64)
        self.F[0, 4] = 1.0
        self.F[1, 5] = 1.0
        self.F[2, 6] = 1.0
        self.H = np.zeros((4, 7), dtype=np.float64)
        self.H[0, 0] = 1.0
        self.H[1, 1] = 1.0
        self.H[2, 2] = 1.0
        self.H[3, 3] = 1.0
        self.P = np.eye(7, dtype=np.float64)
        self.P[4:, 4:] *= 100.0
        self.P[2, 2] *= 10.0
        self.Q = np.eye(7, dtype=np.float64)
        self.Q[4:, 4:] *= 0.5
        self.I = np.eye(7, dtype=np.float64)

    def get_measurement_noise(self) -> np.ndarray:
        """
        Matriks kovarians noise pengukuran R adaptif (Full HD / dynamic scale).
        Menghindari ill-conditioning pada bounding box kendaraan besar (truk/bus):
        - Varians posisi pusat (cx, cy): 9.0 (sigma = 3.0 px)
        - Varians luas area (s): proporsional terhadap estimasi luas box, sigma_s ~ 8% luas
        - Varians aspek rasio (r = w/h): 0.01 (sigma_r = 0.1)
        """
        current_s = max(float(self.x[2, 0]), 100.0)
        var_s = max(100.0, (0.08 * current_s) ** 2)
        return np.diag([9.0, 9.0, var_s, 0.01]).astype(np.float64)

    @property
    def R(self) -> np.ndarray:
        return self.get_measurement_noise()

    def predict(self) -> np.ndarray:
        if self.x[2, 0] + self.x[6, 0] <= 0:
            self.x[6, 0] = 0.0
        self.x = self.F @ self.x
        self.P = self.F @ self.P @ self.F.T + self.Q
        return self.x[:4, 0].copy()

    def innovation_covariance(self) -> np.ndarray:
        return self.H @ self.P @ self.H.T + self.get_measurement_noise()

    def mahalanobis(self, bbox: list[int]) -> float:
        z = bbox_to_z(bbox).reshape(4, 1)
        y = z - self.H @ self.x
        s = self.innovation_covariance()
        try:
            s_inv = np.linalg.inv(s)
        except np.linalg.LinAlgError:
            s_inv = np.linalg.pinv(s)
        d2 = float((y.T @ s_inv @ y)[0, 0])
        return max(0.0, d2)

    def update(self, bbox: list[int]) -> None:
        z = bbox_to_z(bbox).reshape(4, 1)
        s = self.innovation_covariance()
        try:
            s_inv = np.linalg.inv(s)
        except np.linalg.LinAlgError:
            s_inv = np.linalg.pinv(s)
        k = self.P @ self.H.T @ s_inv
        y = z - self.H @ self.x
        self.x = self.x + k @ y
        self.P = (self.I - k @ self.H) @ self.P
        self.x[2, 0] = max(self.x[2, 0], 1.0)
        self.x[3, 0] = max(self.x[3, 0], 0.05)

    def bbox(self) -> list[int]:
        return z_to_bbox(self.x[:4, 0])


def _hungarian(cost: np.ndarray) -> list[tuple[int, int]]:
    if cost.size == 0:
        return []
    try:
        from scipy.optimize import linear_sum_assignment

        rows, cols = linear_sum_assignment(cost)
        return list(zip(rows.tolist(), cols.tolist()))
    except Exception:
        used_r: set[int] = set()
        used_c: set[int] = set()
        pairs: list[tuple[int, int]] = []
        flat = [(cost[i, j], i, j) for i in range(cost.shape[0]) for j in range(cost.shape[1])]
        for _, i, j in sorted(flat):
            if i in used_r or j in used_c:
                continue
            used_r.add(i)
            used_c.add(j)
            pairs.append((i, j))
        return pairs


class AssociationTracker:
    """
    Tracker dengan prediksi Kalman dan asosiasi D / D* / D**.
    Prediksi bbox saat YOLO miss-frame membuat objek tetap tampil (ID stabil).
    """

    def __init__(
        self,
        max_disappeared: int = 20,
        max_distance: float = 200.0,
        min_hits: int = 1,
        lambda_consistency: float = 5.0,
        association: str = "quadratic",
        mahalanobis_gate: float = CHI2_GATING_4D,
        iou_match_min: float = 0.25,
    ):
        if association not in ("mahalanobis", "linear", "quadratic"):
            raise ValueError("association harus mahalanobis | linear | quadratic")
        self.max_disappeared = max_disappeared
        self.max_distance = max_distance
        self.min_hits = min_hits
        self.lambda_consistency = lambda_consistency
        self.association = association
        self.mahalanobis_gate = mahalanobis_gate
        self.iou_match_min = iou_match_min
        self._tracks: dict[int, Track] = {}
        self._filters: dict[int, KalmanBoxFilter] = {}
        self._next_id = 1

    @property
    def tracks(self) -> dict[int, Track]:
        return self._tracks

    def reset(self) -> None:
        self._tracks.clear()
        self._filters.clear()
        self._next_id = 1

    def get_stable_tracks(self) -> list[Track]:
        return [t for t in self._tracks.values() if t.age >= self.min_hits]

    def _apply_detection(self, tid: int, track: Track, det: dict) -> None:
        kf = self._filters[tid]
        kf.update(det["bbox"])
        x1, y1, x2, y2 = det["bbox"]
        track.bbox = [x1, y1, x2, y2]
        track.centroid = ((x1 + x2) / 2.0, (y1 + y2) / 2.0)
        track.confidence = det["confidence"]
        track.peak_confidence = max(track.peak_confidence, det["confidence"])
        track.frames_since_seen = 0
        track.age += 1
        track.hits += 1
        track.vote_class(det["class_name"], det["confidence"])
        track.prev_bbox = list(track.bbox)

    def update(self, detections: list[dict]) -> list[Track]:
        existing_ids = set(self._tracks.keys())
        for tid, kf in self._filters.items():
            track = self._tracks[tid]
            track.prev_bbox = list(track.bbox)
            pred_z = kf.predict()
            predicted = z_to_bbox(pred_z)
            track.bbox = predicted
            track.centroid = ((predicted[0] + predicted[2]) / 2.0, (predicted[1] + predicted[3]) / 2.0)

        if not detections:
            return self._mark_misses(set(), existing_ids)

        det_by_class: dict[str, list[dict]] = {}
        for det in detections:
            det_by_class.setdefault(det["class_name"], []).append(det)

        matched_tids: set[int] = set()
        matched_det_ids: set[int] = set()

        for cls, class_dets in det_by_class.items():
            class_tracks = [
                (tid, self._tracks[tid])
                for tid in existing_ids
                if tid in self._tracks and self._tracks[tid].stable_class == cls
            ]
            self._match_group(class_tracks, class_dets, matched_tids, matched_det_ids)

        unmatched_tracks = [
            (tid, self._tracks[tid])
            for tid in existing_ids
            if tid in self._tracks and tid not in matched_tids
        ]
        unmatched_dets = [d for d in detections if id(d) not in matched_det_ids]
        if unmatched_tracks and unmatched_dets:
            self._match_group(unmatched_tracks, unmatched_dets, matched_tids, matched_det_ids, iou_only=True)

        self._mark_misses(matched_tids, existing_ids)

        for det in detections:
            if id(det) in matched_det_ids:
                continue
            self._register(det)

        return list(self._tracks.values())

    def _compute_pair_cost(
        self,
        track: Track,
        kf: KalmanBoxFilter,
        det: dict,
        min_iou: float,
        iou_only: bool,
    ) -> float | None:
        """Hitung cost asosiasi track-deteksi dengan gating; None jika di luar batas gate."""
        prev_box = track.prev_bbox or track.bbox
        t_ij = iou(det["bbox"], prev_box)
        d_ij = kf.mahalanobis(det["bbox"])

        cx = (det["bbox"][0] + det["bbox"][2]) / 2.0
        cy = (det["bbox"][1] + det["bbox"][3]) / 2.0
        dist = ((cx - track.centroid[0]) ** 2 + (cy - track.centroid[1]) ** 2) ** 0.5

        if t_ij < min_iou and dist > self.max_distance * 3.0:
            return None
        if not iou_only and d_ij > self.mahalanobis_gate and t_ij < self.iou_match_min:
            return None
        if iou_only and t_ij < self.iou_match_min and dist > self.max_distance:
            return None

        if iou_only:
            return 1.0 - t_ij
        return association_cost(
            d_ij,
            t_ij,
            formula=self.association,
            lambda_consistency=self.lambda_consistency,
        )

    def _match_group(
        self,
        class_tracks: list[tuple[int, Track]],
        class_dets: list[dict],
        matched_tids: set[int],
        matched_det_ids: set[int],
        *,
        iou_only: bool = False,
    ) -> None:
        if not class_tracks or not class_dets:
            return
        n_t, n_d = len(class_tracks), len(class_dets)
        cost = np.full((n_t, n_d), 1e5, dtype=np.float64)
        min_iou = 0.15 if iou_only else 0.05
        for i, (tid, track) in enumerate(class_tracks):
            if tid in matched_tids:
                continue
            kf = self._filters[tid]
            for j, det in enumerate(class_dets):
                if id(det) in matched_det_ids:
                    continue
                pair_cost = self._compute_pair_cost(track, kf, det, min_iou, iou_only)
                if pair_cost is not None:
                    cost[i, j] = pair_cost

        for i, j in _hungarian(cost):
            if cost[i, j] >= 1e5:
                continue
            tid, track = class_tracks[i]
            det = class_dets[j]
            if tid in matched_tids or id(det) in matched_det_ids:
                continue
            self._apply_detection(tid, track, det)
            matched_tids.add(tid)
            matched_det_ids.add(id(det))

    def _mark_misses(self, matched_tids: set[int], existing_ids: set[int]) -> list[Track]:
        stale: list[int] = []
        for tid in existing_ids:
            track = self._tracks.get(tid)
            if track is None or tid in matched_tids:
                continue
            track.frames_since_seen += 1
            if track.frames_since_seen > self.max_disappeared:
                stale.append(tid)
        for tid in stale:
            self._tracks.pop(tid, None)
            self._filters.pop(tid, None)
        return list(self._tracks.values())

    def _register(self, det: dict) -> None:
        x1, y1, x2, y2 = det["bbox"]
        if (x2 - x1) < 22 or (y2 - y1) < 28 or (x2 - x1) * (y2 - y1) < 700:
            return
        cls = det["class_name"]
        bbox = [x1, y1, x2, y2]
        track = Track(
            track_id=self._next_id,
            class_name=cls,
            centroid=((x1 + x2) / 2.0, (y1 + y2) / 2.0),
            bbox=bbox,
            confidence=det["confidence"],
            peak_confidence=det["confidence"],
            age=1,
            hits=1,
            class_votes={cls: float(det["confidence"])},
            prev_bbox=list(bbox),
        )
        self._filters[self._next_id] = KalmanBoxFilter(bbox)
        self._tracks[self._next_id] = track
        self._next_id += 1


SimpleTracker = AssociationTracker
