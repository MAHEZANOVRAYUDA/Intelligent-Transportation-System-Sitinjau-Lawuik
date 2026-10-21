"""Visualisasi deteksi untuk mode pengembangan."""

from __future__ import annotations

import cv2
import numpy as np

from src.detection.tracker import Track

CLASS_COLORS: dict[str, tuple[int, int, int]] = {
    "motor": (0, 255, 255),   # kuning
    "mobil": (0, 200, 0),     # hijau
    "bus": (255, 140, 0),     # biru-oranye (BGR)
    "truck": (0, 100, 255),   # oranye
}

CLASS_COLORS_BGR = CLASS_COLORS


def draw_counting_line(frame: np.ndarray, line: list[int], color=(0, 0, 255)) -> None:
    x1, y1, x2, y2 = line
    cv2.line(frame, (x1, y1), (x2, y2), color, 3, cv2.LINE_AA)
    cv2.putText(
        frame, "COUNTING LINE", (x1 + 10, y1 - 12),
        cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2, cv2.LINE_AA,
    )


def draw_lane_divider(frame: np.ndarray, line: list[int], inbound_side: str = "left") -> None:
    x1, y1, x2, y2 = line
    cv2.line(frame, (x1, y1), (x2, y2), (255, 255, 0), 2, cv2.LINE_AA)
    cv2.putText(
        frame, f"LANE | IN={inbound_side.upper()}", (x1 + 8, min(y1, y2) + 24),
        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 0), 2, cv2.LINE_AA,
    )


def draw_detection_box(
    frame: np.ndarray,
    bbox: list[int],
    label: str,
    confidence: float,
    track_id: int | None = None,
    color: tuple[int, int, int] | None = None,
) -> None:
    x1, y1, x2, y2 = bbox
    cls_key = label.split()[0].lower()
    c = color or CLASS_COLORS.get(cls_key, (255, 255, 255))

    cv2.rectangle(frame, (x1, y1), (x2, y2), c, 2)
    tag = f"#{track_id} {label} {confidence:.0%}" if track_id else f"{label} {confidence:.0%}"

    (tw, th), _ = cv2.getTextSize(tag, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 2)
    cv2.rectangle(frame, (x1, y1 - th - 10), (x1 + tw + 6, y1), c, -1)
    cv2.putText(frame, tag, (x1 + 3, y1 - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 2, cv2.LINE_AA)


def draw_tracks(frame: np.ndarray, tracks: list[Track]) -> None:
    for track in tracks:
        label = track.stable_class if hasattr(track, "stable_class") else track.class_name
        draw_detection_box(
            frame,
            track.bbox,
            label.upper(),
            track.confidence,
            track_id=track.track_id,
        )
        cx, cy = int(track.centroid[0]), int(track.centroid[1])
        cv2.circle(frame, (cx, cy), 4, (255, 255, 255), -1)


def draw_raw_detections(frame: np.ndarray, detections: list[dict]) -> None:
    for det in detections:
        draw_detection_box(
            frame,
            det["bbox"],
            det["class_name"].upper(),
            det["confidence"],
        )


def draw_hud(
    frame: np.ndarray,
    *,
    gate_id: str,
    inference_fps: float,
    detection_count: int,
    track_count: int,
    counts_in: dict[str, int],
    counts_out: dict[str, int],
) -> None:
    h, w = frame.shape[:2]
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (w, 110), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.55, frame, 0.45, 0, frame)

    lines = [
        f"DEV MODE | Gerbang {gate_id} | Infer {inference_fps:.1f} FPS",
        f"Deteksi: {detection_count} | Track: {track_count}",
        (
            f"IN  M:{counts_in.get('motor',0)} C:{counts_in.get('mobil',0)} "
            f"B:{counts_in.get('bus',0)} T:{counts_in.get('truck',0)}"
        ),
        (
            f"OUT M:{counts_out.get('motor',0)} C:{counts_out.get('mobil',0)} "
            f"B:{counts_out.get('bus',0)} T:{counts_out.get('truck',0)}"
        ),
    ]
    for i, text in enumerate(lines):
        cv2.putText(
            frame, text, (12, 22 + i * 22),
            cv2.FONT_HERSHEY_SIMPLEX, 0.55, (220, 220, 220), 1, cv2.LINE_AA,
        )


def annotate_frame(
    frame: np.ndarray,
    *,
    line: list[int],
    tracks: list[Track],
    detections: list[dict],
    gate_id: str,
    inference_fps: float,
    counts_in: dict[str, int],
    counts_out: dict[str, int],
    show_raw: bool = False,
    lane_divider: list[int] | None = None,
    inbound_side: str = "left",
    draw_lines: bool = False,
) -> np.ndarray:
    annotated = frame.copy()
    if draw_lines:
        draw_counting_line(annotated, line)
        if lane_divider and len(lane_divider) == 4:
            draw_lane_divider(annotated, lane_divider, inbound_side)

    if show_raw:
        draw_raw_detections(annotated, detections)
    else:
        draw_tracks(annotated, tracks)

    draw_hud(
        annotated,
        gate_id=gate_id,
        inference_fps=inference_fps,
        detection_count=len(detections),
        track_count=len(tracks),
        counts_in=counts_in,
        counts_out=counts_out,
    )
    return annotated


def encode_jpeg(frame: np.ndarray, quality: int = 85) -> bytes | None:
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return buf.tobytes() if ok else None
