"""Konfigurasi aplikasi Sitinjau Laut Traffic Monitoring."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings

ROOT_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT_DIR / "config" / "settings.yaml"

load_dotenv(ROOT_DIR / ".env")


class VehicleConfig(BaseModel):
    length_m: float
    coco_classes: list[str]


class GateConfig(BaseModel):
    name: str
    direction: str
    counting_line: list[int]
    entry_direction: str
    lane_divider: list[int] | None = None
    inbound_side: str = "left"


class TrafficStatusThresholds(BaseModel):
    lancar_max: float = 50.0
    padat_max: float = 75.0


class StreamConfig(BaseModel):
    output_width: int = 1280
    output_height: int = 720
    fps: int = 15
    buffer_size: int = 1
    jpeg_quality: int = 80
    reconnect_delay_sec: int = 5
    max_reconnect_attempts: int = 0


class DetectionConfig(BaseModel):
    model_path: str = "models/yolov8n.pt"
    confidence: float = 0.45
    iou: float = 0.5
    imgsz: int = 640
    device: str = "cpu"
    classes: list[str] = Field(default_factory=lambda: ["motor", "mobil", "bus", "truck"])


class AppSettings(BaseSettings):
    gate_a_rtsp_url: str = ""
    gate_b_rtsp_url: str = ""
    database_url: str = "sqlite:///./data/sitinjau_laut.db"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_debug: bool = False
    detection_enabled: bool = True
    detection_confidence: float = 0.45
    detection_device: str = "cpu"

    model_config = {"env_file": ".env", "extra": "ignore"}


def _load_yaml() -> dict[str, Any]:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


@lru_cache
def get_settings() -> tuple[dict[str, Any], AppSettings]:
    raw = _load_yaml()
    env = AppSettings()
    return raw, env


def get_road_capacity() -> float:
    raw, _ = get_settings()
    return float(raw["road"]["total_capacity_meter_lajur"])


def get_vehicle_lengths() -> dict[str, float]:
    raw, _ = get_settings()
    return {name: cfg["length_m"] for name, cfg in raw["vehicles"].items()}


def get_traffic_thresholds() -> TrafficStatusThresholds:
    raw, _ = get_settings()
    return TrafficStatusThresholds(**raw["traffic_status"])


def get_stream_config() -> StreamConfig:
    raw, _ = get_settings()
    return StreamConfig(**raw["stream"])


def get_detection_config() -> DetectionConfig:
    raw, env = get_settings()
    cfg = DetectionConfig(**raw["detection"])
    # Confidence dari settings.yaml agar eksperimen paper terkendali.
    cfg.device = env.detection_device
    return cfg


def get_gate_config(gate_id: str) -> GateConfig | None:
    raw, _ = get_settings()
    gates = raw.get("gates", {})
    if gate_id not in gates:
        return None
    return GateConfig(**gates[gate_id])


def reload_settings() -> None:
    get_settings.cache_clear()


def _yaml_list(values: list[int]) -> str:
    return "[" + ", ".join(str(int(v)) for v in values) + "]"


def _upsert_gate_key(block: str, key: str, value: str) -> str:
    import re

    pattern = rf"^(\s*){re.escape(key)}:\s*.*$"
    if re.search(pattern, block, flags=re.M):
        return re.sub(pattern, rf"\1{key}: {value}", block, count=1, flags=re.M)
    return re.sub(
        r"(    entry_direction:\s*\w+)",
        rf"\1\n    {key}: {value}",
        block,
        count=1,
    )


def persist_gate_calibration(
    gate_id: str,
    counting_line: list[int],
    entry_direction: str,
    lane_divider: list[int] | None = None,
    inbound_side: str | None = None,
) -> None:
    """Simpan kalibrasi counting line dan lane divider ke settings.yaml."""
    import re

    gate_id = gate_id.upper()
    text = CONFIG_PATH.read_text(encoding="utf-8")
    start = text.find(f"  {gate_id}:")
    if start < 0:
        raise ValueError(f"Gerbang {gate_id} tidak ditemukan di settings.yaml")

    rest = text[start + 1 :]
    next_gate = re.search(r"\n  [A-Z]:", rest)
    end = start + 1 + next_gate.start() if next_gate else len(text)
    block = text[start:end]

    if "counting_line:" not in block:
        raise ValueError(f"counting_line tidak ada pada gerbang {gate_id}")

    block = _upsert_gate_key(block, "counting_line", _yaml_list(counting_line))
    block = _upsert_gate_key(block, "entry_direction", entry_direction)
    if lane_divider is not None and len(lane_divider) == 4:
        block = _upsert_gate_key(block, "lane_divider", _yaml_list(lane_divider))
    if inbound_side:
        block = _upsert_gate_key(block, "inbound_side", inbound_side)

    CONFIG_PATH.write_text(text[:start] + block + text[end:], encoding="utf-8")
    reload_settings()


def get_coco_to_local_map() -> dict[str, str]:
    raw, _ = get_settings()
    mapping: dict[str, str] = {}
    for local_name, cfg in raw["vehicles"].items():
        for coco in cfg["coco_classes"]:
            mapping[coco] = local_name
    return mapping


def ensure_directories() -> None:
    for path in ["data", "data/frames", "data/recordings", "models", "logs"]:
        (ROOT_DIR / path).mkdir(parents=True, exist_ok=True)
