"""Konfigurasi aplikasi Sitinjau Laut Traffic Monitoring."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
try:
    from dotenv import load_dotenv
    _has_dotenv = True
except ImportError:
    _has_dotenv = False

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings

ROOT_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT_DIR / "config" / "settings.yaml"

if _has_dotenv:
    load_dotenv(ROOT_DIR / ".env")


class VehicleConfig(BaseModel):
    length_m: float
    coco_classes: list[str]


class GateConfig(BaseModel):
    name: str
    location: str = ""
    direction: str
    counting_line: list[int]
    entry_direction: str
    lane_divider: list[int] | None = None
    inbound_side: str = "left"


class TrafficStatusThresholds(BaseModel):
    lancar_max: float = 50.0
    padat_max: float = 75.0


class PKJIEkrConfig(BaseModel):
    mobil: float = 1.00
    motor: float = 0.40
    bus: float = 2.50
    truck: float = 8.90


class PKJISubclassWeights(BaseModel):
    ks: float = 1.50   # Kendaraan Sedang (bus kecil, truk 2-as kecil)
    bb: float = 2.50   # Bus Besar (roda 6+)
    tb: float = 8.90   # Truk Besar (tronton, kontainer, 3-as)


class PKJISubclassesConfig(BaseModel):
    uphill: PKJISubclassWeights = Field(default_factory=lambda: PKJISubclassWeights(ks=1.50, bb=2.50, tb=8.90))
    downhill: PKJISubclassWeights = Field(default_factory=lambda: PKJISubclassWeights(ks=1.20, bb=1.60, tb=2.50))


class PKJICompositionConfig(BaseModel):
    p_bus_ks: float = 0.0     # Proporsi bus mikro/kecil (KS) terhadap seluruh bus
    p_bus_bb: float = 1.0     # Proporsi bus besar (BB) terhadap seluruh bus
    p_truck_ks: float = 0.0   # Proporsi truk kecil/sedang (KS) terhadap seluruh truk
    p_truck_tb: float = 1.0   # Proporsi truk besar/tronton (TB) terhadap seluruh truk


class PKJILosThresholds(BaseModel):
    los_a_max: float = 0.20
    los_b_max: float = 0.44
    los_c_max: float = 0.74
    los_d_max: float = 0.84
    los_e_max: float = 1.00
    lancar_max_ds: float = 0.44
    padat_max_ds: float = 0.84


class PKJIConfig(BaseModel):
    base_capacity_c0: float = 3550.0
    road_width_m: float = 6.5
    factor_fc_w: float = 0.91
    factor_fc_sp: float = 1.00
    factor_fc_sf: float = 0.91
    segment_mode: str = "khusus"
    citation: str = "SE Ditjen Bina Marga No. 21/SE/Db/2023"
    calculation_mode: str = "composite"  # "composite" | "direct"
    ekr: PKJIEkrConfig = Field(default_factory=PKJIEkrConfig)
    subclasses: PKJISubclassesConfig = Field(default_factory=PKJISubclassesConfig)
    composition_ratios: PKJICompositionConfig = Field(default_factory=PKJICompositionConfig)
    los_thresholds: PKJILosThresholds = Field(default_factory=PKJILosThresholds)

    @property
    def practical_capacity_c(self) -> float:
        """Kapasitas ruas praktis C = C0 * FCw * FCsp * FCsf [smp/jam]."""
        return round(self.base_capacity_c0 * self.factor_fc_w * self.factor_fc_sp * self.factor_fc_sf, 2)

    def calculate_composite_ekr(self, direction: str = "menanjak") -> dict[str, float]:
        """
        Menghitung nilai ekspektasi E[emp] berdasarkan proporsi komposisi armada PKJI 2023.
        E[emp_bus]   = P(KS|bus) * emp_KS + P(BB|bus) * emp_BB
        E[emp_truck] = P(KS|truck) * emp_KS + P(TB|truck) * emp_TB
        """
        is_menanjak = direction.lower() in ("menanjak", "in", "up", "naik")
        weights = self.subclasses.uphill if is_menanjak else self.subclasses.downhill
        comp = self.composition_ratios

        bus_sum = comp.p_bus_ks + comp.p_bus_bb
        p_b_ks = (comp.p_bus_ks / bus_sum) if bus_sum > 0 else 0.0
        p_b_bb = (comp.p_bus_bb / bus_sum) if bus_sum > 0 else 1.0

        truck_sum = comp.p_truck_ks + comp.p_truck_tb
        p_t_ks = (comp.p_truck_ks / truck_sum) if truck_sum > 0 else 0.0
        p_t_tb = (comp.p_truck_tb / truck_sum) if truck_sum > 0 else 1.0

        e_bus = round(p_b_ks * weights.ks + p_b_bb * weights.bb, 2)
        e_truck = round(p_t_ks * weights.ks + p_t_tb * weights.tb, 2)

        return {
            "motor": self.ekr.motor,
            "mobil": self.ekr.mobil,
            "bus": e_bus,
            "truck": e_truck,
        }


class StreamConfig(BaseModel):
    output_width: int = 1280
    output_height: int = 720
    fps: int = 15
    buffer_size: int = 1
    jpeg_quality: int = 80
    reconnect_delay_sec: int = 5
    max_reconnect_attempts: int = 0


class TransitConfig(BaseModel):
    avg_speed_kmh: float = 40.0
    estimated_transit_sec: int = 1500
    adaptive_enabled: bool = True
    bpr_alpha: float = 2.5
    bpr_beta: float = 2.0
    max_transit_sec: int = 9000


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


def get_pkji_config() -> PKJIConfig:
    raw, _ = get_settings()
    pkji_raw = raw.get("pkji", {})
    return PKJIConfig(**pkji_raw)


def get_transit_config() -> TransitConfig:
    raw, _ = get_settings()
    transit_raw = raw.get("transit", {})
    return TransitConfig(**transit_raw)


def persist_pkji_params(
    base_capacity_c0: float,
    road_width_m: float,
    factor_fc_w: float,
    factor_fc_sp: float,
    factor_fc_sf: float,
    ekr_motor: float,
    ekr_mobil: float,
    ekr_bus: float,
    ekr_truck: float,
    estimated_transit_sec: int | None = None,
    segment_mode: str | None = None,
    citation: str | None = None,
    calculation_mode: str | None = None,
    p_bus_ks: float | None = None,
    p_bus_bb: float | None = None,
    p_truck_ks: float | None = None,
    p_truck_tb: float | None = None,
    subclass_ks_uphill: float | None = None,
    subclass_bb_uphill: float | None = None,
    subclass_tb_uphill: float | None = None,
    subclass_ks_downhill: float | None = None,
    subclass_bb_downhill: float | None = None,
    subclass_tb_downhill: float | None = None,
) -> None:
    """Menyimpan parameter kalibrasi PKJI 2023 ke settings.yaml secara persisten."""
    import re

    text = CONFIG_PATH.read_text(encoding="utf-8")

    # Helper regex pengganti nilai key numerik dalam text
    def _sub_val(txt: str, key: str, val: Any) -> str:
        return re.sub(rf"({re.escape(key)}:\s*)[0-9.]+", rf"\g<1>{val}", txt, count=1)

    # Helper regex pengganti nilai key string dalam text
    def _sub_str(txt: str, key: str, val: str) -> str:
        pattern = rf"^(\s*{re.escape(key)}:\s*).*$"
        if re.search(pattern, txt, flags=re.M):
            return re.sub(pattern, rf'\g<1>"{val}"', txt, count=1, flags=re.M)
        # Jika belum ada, tambahkan di bawah pkji:
        pkji_idx = txt.find("pkji:")
        if pkji_idx >= 0:
            insert_pos = txt.find("\n", pkji_idx) + 1
            return txt[:insert_pos] + f'  {key}: "{val}"\n' + txt[insert_pos:]
        return txt

    # Update parameter utama PKJI
    text = _sub_val(text, "base_capacity_c0", float(base_capacity_c0))
    text = _sub_val(text, "road_width_m", float(road_width_m))
    text = _sub_val(text, "factor_fc_w", float(factor_fc_w))
    text = _sub_val(text, "factor_fc_sp", float(factor_fc_sp))
    text = _sub_val(text, "factor_fc_sf", float(factor_fc_sf))

    if segment_mode:
        text = _sub_str(text, "segment_mode", segment_mode)
    if citation:
        text = _sub_str(text, "citation", citation)
    if calculation_mode:
        text = _sub_str(text, "calculation_mode", calculation_mode)

    # Update ekr dalam blok pkji
    pkji_idx = text.find("pkji:")
    if pkji_idx >= 0:
        pkji_block = text[pkji_idx:]
        gates_idx = pkji_block.find("\ngates:")
        if gates_idx < 0:
            gates_idx = len(pkji_block)
        sub_block = pkji_block[:gates_idx]

        sub_block = re.sub(r"(mobil:\s*)[0-9.]+", rf"\g<1>{float(ekr_mobil)}", sub_block, count=1)
        sub_block = re.sub(r"(motor:\s*)[0-9.]+", rf"\g<1>{float(ekr_motor)}", sub_block, count=1)
        sub_block = re.sub(r"(bus:\s*)[0-9.]+", rf"\g<1>{float(ekr_bus)}", sub_block, count=1)
        sub_block = re.sub(r"(truck:\s*)[0-9.]+", rf"\g<1>{float(ekr_truck)}", sub_block, count=1)

        # Update komposisi jika ada
        if p_bus_ks is not None:
            sub_block = re.sub(r"(p_bus_ks:\s*)[0-9.]+", rf"\g<1>{float(p_bus_ks)}", sub_block, count=1)
        if p_bus_bb is not None:
            sub_block = re.sub(r"(p_bus_bb:\s*)[0-9.]+", rf"\g<1>{float(p_bus_bb)}", sub_block, count=1)
        if p_truck_ks is not None:
            sub_block = re.sub(r"(p_truck_ks:\s*)[0-9.]+", rf"\g<1>{float(p_truck_ks)}", sub_block, count=1)
        if p_truck_tb is not None:
            sub_block = re.sub(r"(p_truck_tb:\s*)[0-9.]+", rf"\g<1>{float(p_truck_tb)}", sub_block, count=1)

        text = text[:pkji_idx] + sub_block + pkji_block[gates_idx:]

    if estimated_transit_sec is not None:
        text = _sub_val(text, "estimated_transit_sec", int(estimated_transit_sec))

    CONFIG_PATH.write_text(text, encoding="utf-8")
    reload_settings()


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
