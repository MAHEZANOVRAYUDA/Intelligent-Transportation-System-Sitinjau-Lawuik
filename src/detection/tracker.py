"""Simple centroid tracker untuk menghindari double-count."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


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
    class_votes: dict[str, int] = field(default_factory=dict)

    @property
    def stable_class(self) -> str:
        if not self.class_votes:
            return self.class_name
        return max(self.class_votes, key=self.class_votes.get)

    def vote_class(self, class_name: str) -> None:
        self.class_votes[class_name] = self.class_votes.get(class_name, 0) + 1
        self.class_name = self.stable_class


class SimpleTracker:
    """
    Centroid-based tracker dengan matching per kelas dan voting klasifikasi.
    """

    def __init__(
        self,
        max_disappeared: int = 20,
        max_distance: float = 200.0,
        min_hits: int = 3,
    ):
        self.max_disappeared = max_disappeared
        self.max_distance = max_distance
        self.min_hits = min_hits
        self._tracks: dict[int, Track] = {}
        self._next_id = 1

    @property
    def tracks(self) -> dict[int, Track]:
        return self._tracks

    def update(self, detections: list[dict]) -> list[Track]:
        if not detections:
            for track_id in list(self._tracks.keys()):
                self._tracks[track_id].frames_since_seen += 1
                if self._tracks[track_id].frames_since_seen > self.max_disappeared:
                    del self._tracks[track_id]
            return list(self._tracks.values())

        input_centroids: list[tuple[float, float, dict]] = []
        for det in detections:
            x1, y1, x2, y2 = det["bbox"]
            cx = (x1 + x2) / 2
            cy = (y1 + y2) / 2
            input_centroids.append((cx, cy, det))

        if not self._tracks:
            for _, _, det in input_centroids:
                self._register(det)
            return list(self._tracks.values())

        track_ids = list(self._tracks.keys())
        used_tracks: set[int] = set()
        used_inputs: set[int] = set()

        for i, (cx, cy, det) in enumerate(input_centroids):
            det_class = det["class_name"]
            best_dist = float("inf")
            best_tid: int | None = None

            for tid in track_ids:
                if tid in used_tracks:
                    continue
                track = self._tracks[tid]
                if track.stable_class != det_class:
                    continue
                tx, ty = track.centroid
                dist = ((cx - tx) ** 2 + (cy - ty) ** 2) ** 0.5
                if dist < best_dist and dist < self.max_distance:
                    best_dist = dist
                    best_tid = tid

            if best_tid is not None:
                track = self._tracks[best_tid]
                x1, y1, x2, y2 = det["bbox"]
                track.centroid = (cx, cy)
                track.bbox = [x1, y1, x2, y2]
                track.confidence = det["confidence"]
                track.peak_confidence = max(track.peak_confidence, det["confidence"])
                track.frames_since_seen = 0
                track.age += 1
                track.vote_class(det_class)
                used_tracks.add(best_tid)
                used_inputs.add(i)
            else:
                self._register(det)
                used_inputs.add(i)

        for tid in track_ids:
            if tid not in used_tracks:
                self._tracks[tid].frames_since_seen += 1
                if self._tracks[tid].frames_since_seen > self.max_disappeared:
                    del self._tracks[tid]

        return list(self._tracks.values())

    def reset(self) -> None:
        self._tracks.clear()
        self._next_id = 1

    def get_stable_tracks(self) -> list[Track]:
        return [t for t in self._tracks.values() if t.age >= self.min_hits]

    def _register(self, det: dict) -> None:
        x1, y1, x2, y2 = det["bbox"]
        cx = (x1 + x2) / 2
        cy = (y1 + y2) / 2
        cls = det["class_name"]
        track = Track(
            track_id=self._next_id,
            class_name=cls,
            centroid=(cx, cy),
            bbox=det["bbox"],
            confidence=det["confidence"],
            peak_confidence=det["confidence"],
            age=1,
            class_votes={cls: 1},
        )
        self._tracks[self._next_id] = track
        self._next_id += 1
