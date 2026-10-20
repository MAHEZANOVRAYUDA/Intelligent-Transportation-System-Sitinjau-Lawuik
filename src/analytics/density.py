"""Perhitungan kapasitas jalan dan status lalu lintas berdasarkan PKJI 2023.

Pedoman Kapasitas Jalan Indonesia (PKJI 2023 — Ditjen Bina Marga No. 09/P/BM/2023)
Ruas: Jalan Luar Kota / Antarkota 2/2 TT Medan Bukit/Gunung (Sitinjau Lauik)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

from src.config import (
    get_pkji_config,
    get_road_capacity,
    get_settings,
    get_traffic_thresholds,
    get_transit_config,
    get_vehicle_lengths,
)


class TrafficLevel(str, Enum):
    LANCAR = "lancar"
    PADAT = "padat"
    MACET = "macet"


class LoSLevel(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    E = "E"
    F = "F"


@dataclass
class VehicleCount:
    motor: int = 0
    mobil: int = 0
    bus: int = 0
    truck: int = 0

    def to_dict(self) -> dict[str, int]:
        return {"motor": self.motor, "mobil": self.mobil, "bus": self.bus, "truck": self.truck}

    def total(self) -> int:
        return self.motor + self.mobil + self.bus + self.truck


@dataclass
class OnRoadVehicle:
    class_name: str
    entered_at: datetime
    gate: str


@dataclass
class CrossingEvent:
    timestamp: datetime
    class_name: str
    ekr_value: float
    gate: str
    is_entry: bool = True


@dataclass
class TrafficSnapshot:
    timestamp: datetime
    on_road: VehicleCount
    on_road_smp: float
    volume_q_smp_jam: float
    capacity_c_smp_jam: float
    degree_of_saturation: float
    los: str
    status: TrafficLevel
    human_message: str
    counts_in: VehicleCount
    counts_out: VehicleCount
    ekr_weights: dict[str, float]
    hourly_trend: list[dict]
    composite_meta: dict | None = None
    adaptive_transit_sec: int = 1500
    estimated_speed_kmh: float = 40.0
    # Backwards compatibility fields
    volume_used_meter_lajur: float = 0.0
    capacity_meter_lajur: float = 56100.0
    utilization_percent: float = 0.0


def interpolate_fc_w(width_m: float) -> float:
    """
    Interpolasi linier faktor penyesuaian lebar jalur lalu lintas FCw (PKJI 2023).
    Berdasarkan SE Ditjen Bina Marga No. 21/SE/Db/2023 untuk jalan 2/2 TT kelandaian khusus Sitinjau Lauik:
    - We <= 5.0 m -> 0.69
    - We == 6.0 m -> 0.82
    - We == 6.5 m -> 0.91 (interpolasi linier antara 6.0m dan 7.0m)
    - We == 7.0 m -> 1.00
    - We >= 8.0 m -> 1.08
    """
    if width_m <= 5.0:
        return 0.69
    elif width_m <= 6.0:
        return round(0.69 + ((width_m - 5.0) / 1.0) * (0.82 - 0.69), 2)
    elif width_m <= 7.0:
        return round(0.82 + ((width_m - 6.0) / 1.0) * (1.00 - 0.82), 2)
    elif width_m <= 8.0:
        return round(1.00 + ((width_m - 7.0) / 1.0) * (1.08 - 1.00), 2)
    else:
        return 1.08


def get_ekr(class_name: str, direction: str = "menanjak") -> float:
    """
    Mengambil bobot ekr kendaraan berbobot arah (PKJI 2023 - SE No. 21/SE/Db/2023).
    Mendukung model Composite Expected EMP (E[emp]) berdasarkan proporsi armada
    Kendaraan Sedang (KS), Bus Besar (BB), dan Truk Besar (TB).
    Arah 'menanjak' / 'in' / 'up': beban kelandaian tanjakan curam Sitinjau Lauik (>8%).
    Arah 'menurun' / 'out' / 'down': kelandaian menurun, perlambatan truk normal.
    """
    pkji = get_pkji_config()
    is_menanjak = direction.lower() in ("menanjak", "in", "up", "naik")
    if getattr(pkji, "calculation_mode", "composite") == "composite":
        weights = pkji.calculate_composite_ekr(direction)
        return float(weights.get(class_name, 1.0))

    if is_menanjak:
        ekr_dict = pkji.ekr.model_dump()
        return float(ekr_dict.get(class_name, 1.0))
    else:
        # Arah menurun (Solok -> Padang): perlambatan tidak ekstrem seperti tanjakan
        downhill_ekr = {
            "motor": pkji.ekr.motor,
            "mobil": pkji.ekr.mobil,
            "bus": pkji.subclasses.downhill.bb,
            "truck": pkji.subclasses.downhill.tb,
        }
        return float(downhill_ekr.get(class_name, 1.0))


class RoadOccupancyManager:
    """
    Mesin Telemetri Lalu Lintas Terpadu Sitinjau Lauik (PKJI 2023).

    Menghitung:
    - Volume Arus (Q) dalam smp/jam
    - Kapasitas Ruas Praktis (C) dalam smp/jam
    - Derajat Kejenuhan (DS = Q/C)
    - Tingkat Pelayanan (Level of Service / LoS A - F)
    - Status Komando (LANCAR, PADAT, MACET)
    - Riwayat Tren Jam-jaman 24 Jam
    """

    def __init__(self):
        self._lengths = get_vehicle_lengths()
        self._capacity_legacy = get_road_capacity()
        self._thresholds_legacy = get_traffic_thresholds()
        raw, _ = get_settings()
        self._transit_sec = int(raw.get("transit", {}).get("estimated_transit_sec", 1485))

        self._on_road: list[OnRoadVehicle] = []
        self._counts_in = VehicleCount()
        self._counts_out = VehicleCount()
        self._dual_gate_mode = False

        # Riwayat event perlintasan untuk perhitungan rolling-window Q
        self._recent_events: list[CrossingEvent] = []
        # Riwayat per jam (0..23) untuk tren hari ini
        self._hourly_counts: dict[int, dict[str, int]] = {
            h: {"motor": 0, "mobil": 0, "bus": 0, "truck": 0} for h in range(24)
        }

    def set_dual_gate_mode(self, enabled: bool) -> None:
        self._dual_gate_mode = enabled

    def get_ekr(self, class_name: str, direction: str = "menanjak") -> float:
        return get_ekr(class_name, direction)

    def _get_ekr(self, class_name: str) -> float:
        return get_ekr(class_name, "menanjak")

    def register_entry(self, class_name: str, gate: str = "A", direction: str = "menanjak") -> None:
        now = datetime.now()
        self._on_road.append(OnRoadVehicle(class_name=class_name, entered_at=now, gate=gate))
        attr = class_name if hasattr(self._counts_in, class_name) else None
        if attr:
            setattr(self._counts_in, class_name, getattr(self._counts_in, class_name) + 1)

        ekr_val = self.get_ekr(class_name, direction)
        self._recent_events.append(
            CrossingEvent(timestamp=now, class_name=class_name, ekr_value=ekr_val, gate=gate, is_entry=True)
        )
        if attr and 0 <= now.hour < 24:
            self._hourly_counts[now.hour][attr] += 1

    def register_exit(self, class_name: str, gate: str = "B", direction: str = "menurun") -> None:
        now = datetime.now()
        # 1. Selalu tambahkan counter keluar (Konservasi Massa Counter)
        attr = class_name if hasattr(self._counts_out, class_name) else None
        if attr:
            setattr(self._counts_out, attr, getattr(self._counts_out, attr) + 1)

        # 2. Catat event perlintasan keluar dengan bobot EKR menurun
        ekr_val = self.get_ekr(class_name, direction)
        self._recent_events.append(
            CrossingEvent(timestamp=now, class_name=class_name, ekr_value=ekr_val, gate=gate, is_entry=False)
        )

        # 3. Catat volume per jam (total aktivitas koridor)
        if attr and 0 <= now.hour < 24:
            self._hourly_counts[now.hour][attr] += 1

        # 4. Pengurangan on_road antrean koridor
        for i, v in enumerate(self._on_road):
            if v.class_name == class_name:
                self._on_road.pop(i)
                break

    def reset(self) -> None:
        self._on_road.clear()
        self._counts_in = VehicleCount()
        self._counts_out = VehicleCount()
        self._recent_events.clear()
        self._hourly_counts = {h: {"motor": 0, "mobil": 0, "bus": 0, "truck": 0} for h in range(24)}

    def get_adaptive_transit_sec(self) -> int:
        """
        Estimasi Waktu Tempuh Adaptif (Adaptive Transit Delay).
        Menerapkan fungsi tundaan kemacetan berbasis BPR (Bureau of Public Roads) & PKJI 2023:
            T(DS) = T_0 * (1 + alpha * DS^beta)
        di mana:
        - T_0: Waktu tempuh saat arus bebas (free-flow, default 1500s / 25 menit @ 40 km/jam).
        - DS: Derajat kejenuhan efektif pada koridor.
        - alpha = 2.5 (faktor perlambatan tanjakan ekstrem Sitinjau Lauik >8%).
        - beta = 2.0 (eksponen akselerasi kemacetan).
        - Cap maksimum = 9000s (2.5 jam, selaras dengan batas Soft TTL koridor).

        Mencegah antrean kendaraan luruh semu saat jalanan sebenarnya macet total.
        """
        transit_cfg = get_transit_config()
        base_sec = int(transit_cfg.estimated_transit_sec)
        if not transit_cfg.adaptive_enabled:
            return base_sec

        alpha = float(transit_cfg.bpr_alpha)
        beta = float(transit_cfg.bpr_beta)
        max_sec = int(transit_cfg.max_transit_sec)

        c = self.calculate_capacity_c()
        # 1. Rasio laju arus kedatangan (rolling window 15 menit)
        fifteen_min_ago = datetime.now() - timedelta(minutes=15)
        recent_15m = [e for e in self._recent_events if e.timestamp > fifteen_min_ago]
        ds_crossing = 0.0
        if recent_15m and c > 0:
            total_smp_15m = sum(e.ekr_value for e in recent_15m)
            q_crossing = total_smp_15m * (60.0 / 15.0)
            ds_crossing = q_crossing / c

        # 2. Beban muatan aktif koridor terhadap kapasitas dasar waktu bebas
        smp_active = self.calculate_on_road_smp()
        base_hours = max(base_sec / 3600.0, 0.05)
        ds_load = (smp_active / base_hours) / c if c > 0 else 0.0

        ds_eff = max(ds_crossing, ds_load)
        if ds_eff <= 0.05:
            return base_sec

        delay_factor = 1.0 + alpha * (ds_eff ** beta)
        adaptive_sec = int(round(base_sec * delay_factor))
        return min(max(adaptive_sec, base_sec), max_sec)

    def get_estimated_speed_kmh(self) -> float:
        """Estimasi kecepatan rata-rata koridor saat ini berdasarkan waktu transit adaptif."""
        raw, _ = get_settings()
        length_km = float(raw.get("road", {}).get("length_km", 16.5))
        transit_sec = self.get_adaptive_transit_sec()
        hours = max(transit_sec / 3600.0, 0.01)
        return round(length_km / hours, 1)

    def _expire_transit(self) -> None:
        """
        Peluruhan waktu transit & pembersihan riwayat event rolling window.
        - Event crossing window 1 jam SELALU dibersihkan (mencegah memory leak).
        - Mode Dual Gate: Menerapkan Soft TTL (Maximum Corridor Residence Time 2.5 jam / 9000s)
          untuk mencegah cumulative drift (kendaraan hantu akibat miss-deteksi atau singgah di rest area).
        - Mode Single Gate: Peluruhan adaptif (Adaptive Transit Delay) mengikuti
          tingkat kejenuhan koridor, mempertahankan antrean saat macet ekstrem.
        """
        now = datetime.now()
        transit_sec = self.get_adaptive_transit_sec()
        self._transit_sec = transit_sec

        # 1. Bersihkan recent events yang lebih lama dari 1 jam (Memory Safety mutlak)
        event_cutoff = now - timedelta(hours=1)
        self._recent_events = [e for e in self._recent_events if e.timestamp > event_cutoff]

        # 2. Peluruhan antrean koridor
        if self._dual_gate_mode:
            max_corridor_residence_sec = 9000  # 2.5 jam
            corridor_cutoff = now - timedelta(seconds=max_corridor_residence_sec)
            self._on_road = [v for v in self._on_road if v.entered_at > corridor_cutoff]
        else:
            # Single Gate: Gunakan waktu transit adaptif yang memanjang saat macet
            cutoff = now - timedelta(seconds=transit_sec)
            self._on_road = [v for v in self._on_road if v.entered_at > cutoff]

    def _count_on_road(self) -> VehicleCount:
        counts = VehicleCount()
        for v in self._on_road:
            setattr(counts, v.class_name, getattr(counts, v.class_name) + 1)
        return counts

    def calculate_on_road_smp(self) -> float:
        """Menghitung total beban kendaraan aktif di jalan dalam satuan smp."""
        counts = self._count_on_road()
        pkji = get_pkji_config()
        ekr = pkji.ekr
        return round(
            counts.mobil * ekr.mobil
            + counts.motor * ekr.motor
            + counts.bus * ekr.bus
            + counts.truck * ekr.truck,
            2,
        )

    def calculate_volume_q_smp_jam(self) -> float:
        """
        Menghitung Volume Arus Q (smp/jam) dinamis DUA ARAH (PKJI 2023).
        Sesuai PKJI 2023 untuk Jalan Luar Kota 2/2 TT, Kapasitas C adalah
        kapasitas total kedua arah. Oleh karena itu volume arus Q wajib
        mencakup akumulasi kedua arah (IN + OUT) dengan EKR masing-masing:
        Q_total = Q_in (ekr naik) + Q_out (ekr turun).
        """
        smp_active = self.calculate_on_road_smp()
        transit_sec = self.get_adaptive_transit_sec() if not self._dual_gate_mode else self._transit_sec
        transit_hours = max(transit_sec / 3600.0, 0.05)

        # Pendekatan Continuous Dynamic In-Transit Load
        q_dynamic = smp_active / transit_hours

        # Pendekatan Rolling window crossing events 15 menit untuk DUA ARAH (IN + OUT)
        fifteen_min_ago = datetime.now() - timedelta(minutes=15)
        recent_15m = [e for e in self._recent_events if e.timestamp > fifteen_min_ago]
        if recent_15m:
            in_smp = sum(e.ekr_value for e in recent_15m if e.is_entry)
            out_smp = sum(e.ekr_value for e in recent_15m if not e.is_entry)
            total_smp_15m = in_smp + out_smp
            q_crossing = total_smp_15m * (60.0 / 15.0)  # Proyeksikan 15 menit ke 1 jam
            return round(max(q_dynamic, q_crossing), 1)

        return round(q_dynamic, 1)

    def calculate_capacity_c(self) -> float:
        """Kapasitas ruas praktis C = C0 * FCw * FCsp * FCsf [smp/jam]."""
        pkji = get_pkji_config()
        return pkji.practical_capacity_c

    def calculate_degree_of_saturation(self) -> float:
        """Derajat Kejenuhan DS = Q / C."""
        q = self.calculate_volume_q_smp_jam()
        c = self.calculate_capacity_c()
        if c <= 0:
            return 0.0
        return round(q / c, 3)

    def get_los(self, ds: float | None = None) -> LoSLevel:
        val = ds if ds is not None else self.calculate_degree_of_saturation()
        pkji = get_pkji_config()
        th = pkji.los_thresholds

        if val <= th.los_a_max:
            return LoSLevel.A
        if val <= th.los_b_max:
            return LoSLevel.B
        if val <= th.los_c_max:
            return LoSLevel.C
        if val <= th.los_d_max:
            return LoSLevel.D
        if val <= th.los_e_max:
            return LoSLevel.E
        return LoSLevel.F

    def get_status(self, ds: float | None = None) -> TrafficLevel:
        val = ds if ds is not None else self.calculate_degree_of_saturation()
        pkji = get_pkji_config()
        th = pkji.los_thresholds

        if val <= th.lancar_max_ds:
            return TrafficLevel.LANCAR
        if val <= th.padat_max_ds:
            return TrafficLevel.PADAT
        return TrafficLevel.MACET

    def get_human_message(self, status: TrafficLevel, los: LoSLevel) -> str:
        speed = self.get_estimated_speed_kmh()
        transit_min = round(self.get_adaptive_transit_sec() / 60)
        if status == TrafficLevel.LANCAR:
            return f"Lalu lintas lancar (~{speed} km/jam). Estimasi waktu tempuh {transit_min} menit."
        if status == TrafficLevel.PADAT:
            return f"Arus padat di tanjakan (~{speed} km/jam). Estimasi waktu tempuh {transit_min} menit. Waspadai truk lambat."
        return f"Macet di jalur tanjakan (~{speed} km/jam). Estimasi waktu tempuh {transit_min} menit. Antrean padat, pertimbangkan tunda perjalanan."

    def get_hourly_trend(self) -> list[dict]:
        """Menghasilkan data tren 24 jam untuk grafik dashboard."""
        pkji = get_pkji_config()
        ekr = pkji.ekr
        c = pkji.practical_capacity_c
        th = pkji.los_thresholds

        now = datetime.now()
        current_hour = now.hour

        # Laju arus real-time saat ini
        current_q = self.calculate_volume_q_smp_jam()
        current_ds = self.calculate_degree_of_saturation()
        current_los = self.get_los(current_ds).value
        current_status = self.get_status(current_ds).value

        trend = []
        for h in range(24):
            counts = self._hourly_counts[h]
            is_current = (h == current_hour)
            is_future = (h > current_hour)

            if is_current:
                # Jam berjalan: selaraskan dengan laju arus Q aktif (smp/jam)
                # agar titik grafik persis sejajar dengan kartu status telemetri utama (DS 96% -> Macet)
                vol = current_q
                ds = current_ds
                los_str = current_los
                status_str = current_status
            elif is_future:
                # Jam masa depan: belum ada rekaman lapangan (diisi None agar tidak ditarik ke garis 0)
                vol = None
                ds = None
                los_str = None
                status_str = None
            else:
                # Jam masa lalu: dihitung dari akumulasi 1 jam penuh
                smp = (
                    counts["mobil"] * ekr.mobil
                    + counts["motor"] * ekr.motor
                    + counts["bus"] * ekr.bus
                    + counts["truck"] * ekr.truck
                )
                vol = round(smp, 1)
                ds = round(smp / c, 3) if c > 0 else 0.0

                if ds <= th.los_a_max:
                    los_str = "A"
                elif ds <= th.los_b_max:
                    los_str = "B"
                elif ds <= th.los_c_max:
                    los_str = "C"
                elif ds <= th.los_d_max:
                    los_str = "D"
                elif ds <= th.los_e_max:
                    los_str = "E"
                else:
                    los_str = "F"
                status_str = self.get_status(ds).value

            trend.append(
                {
                    "hour": f"{h:02d}:00",
                    "volume_smp": vol,
                    "capacity_smp": c,
                    "degree_of_saturation": ds,
                    "los": los_str,
                    "status": status_str,
                    "counts": dict(counts),
                    "is_current": is_current,
                    "is_future": is_future,
                }
            )
        return trend

    # --- Backwards Compatibility Helpers ---
    def calculate_volume_used(self) -> float:
        counts = self._count_on_road()
        total = 0.0
        for cls, length in self._lengths.items():
            total += getattr(counts, cls) * length
        return total

    def get_utilization_percent(self) -> float:
        ds = self.calculate_degree_of_saturation()
        return min(round(ds * 100.0, 2), 100.0)

    def get_snapshot(self) -> TrafficSnapshot:
        self._expire_transit()
        on_road = self._count_on_road()
        on_road_smp = self.calculate_on_road_smp()
        q = self.calculate_volume_q_smp_jam()
        c = self.calculate_capacity_c()
        ds = self.calculate_degree_of_saturation()
        los = self.get_los(ds)
        status = self.get_status(ds)
        msg = self.get_human_message(status, los)
        pkji = get_pkji_config()

        # Legacy meter-lajur calculations
        volume_used_legacy = self.calculate_volume_used()
        utilization_legacy = self.get_utilization_percent()

        composite_meta = {
            "calculation_mode": getattr(pkji, "calculation_mode", "composite"),
            "subclasses": pkji.subclasses.model_dump(),
            "composition_ratios": pkji.composition_ratios.model_dump(),
            "effective_ekr_uphill": pkji.calculate_composite_ekr("menanjak"),
            "effective_ekr_downhill": pkji.calculate_composite_ekr("menurun"),
        }

        # Jika dalam mode composite, ekr_weights mencerminkan nilai efektif aktual tanjakan
        effective_uphill = composite_meta["effective_ekr_uphill"] if pkji.calculation_mode == "composite" else pkji.ekr.model_dump()

        return TrafficSnapshot(
            timestamp=datetime.now(),
            on_road=on_road,
            on_road_smp=on_road_smp,
            volume_q_smp_jam=q,
            capacity_c_smp_jam=c,
            degree_of_saturation=ds,
            los=los.value,
            status=status,
            human_message=msg,
            counts_in=VehicleCount(**self._counts_in.to_dict()),
            counts_out=VehicleCount(**self._counts_out.to_dict()),
            ekr_weights=effective_uphill,
            hourly_trend=self.get_hourly_trend(),
            composite_meta=composite_meta,
            adaptive_transit_sec=self.get_adaptive_transit_sec(),
            estimated_speed_kmh=self.get_estimated_speed_kmh(),
            volume_used_meter_lajur=round(volume_used_legacy, 2),
            capacity_meter_lajur=self._capacity_legacy,
            utilization_percent=utilization_legacy,
        )

    def snapshot_to_dict(self, snap: TrafficSnapshot | None = None) -> dict:
        s = snap or self.get_snapshot()
        return {
            "timestamp": s.timestamp.isoformat(),
            "on_road": s.on_road.to_dict(),
            "on_road_total": s.on_road.total(),
            "on_road_smp": s.on_road_smp,
            "volume_q_smp_jam": s.volume_q_smp_jam,
            "capacity_c_smp_jam": s.capacity_c_smp_jam,
            "degree_of_saturation": s.degree_of_saturation,
            "los": s.los,
            "status": s.status.value,
            "human_message": s.human_message,
            "counts_in": s.counts_in.to_dict(),
            "counts_out": s.counts_out.to_dict(),
            "ekr_weights": s.ekr_weights,
            "hourly_trend": s.hourly_trend,
            "composite_meta": s.composite_meta,
            "adaptive_transit_sec": s.adaptive_transit_sec,
            "estimated_speed_kmh": s.estimated_speed_kmh,
            # Legacy fields
            "volume_used_meter_lajur": s.volume_used_meter_lajur,
            "capacity_meter_lajur": s.capacity_meter_lajur,
            "utilization_percent": s.utilization_percent,
        }
