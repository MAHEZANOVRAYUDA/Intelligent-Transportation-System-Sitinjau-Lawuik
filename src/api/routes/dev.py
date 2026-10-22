"""Dev mode API routes."""

from __future__ import annotations

import asyncio
import os
import signal

import cv2
import httpx
import numpy as np
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from src.api import state

router = APIRouter(prefix="/api/dev", tags=["development"])

@router.post("/restart")
async def restart_server():
    """Restart server dengan mengirimkan SIGTERM ke process saat ini."""
    def _restart():
        os.kill(os.getpid(), signal.SIGTERM)
    asyncio.get_event_loop().call_later(0.5, _restart)
    return {"message": "Server akan direstart dalam 0.5 detik."}



class CalibrateRequest(BaseModel):
    counting_line: list[int] | None = Field(default=None, min_length=4, max_length=4)
    entry_direction: str | None = None
    lane_divider: list[int] | None = Field(default=None, min_length=4, max_length=4)
    inbound_side: str | None = None
    persist: bool = False
    reset_counts: bool = True


class PKJIParams(BaseModel):
    base_capacity_c0: float = Field(default=3550.0, ge=1000.0, le=6000.0)
    road_width_m: float = Field(default=6.5, ge=4.0, le=12.0)
    factor_fc_w: float = Field(default=0.91, ge=0.5, le=1.5)
    factor_fc_sp: float = Field(default=1.00, ge=0.5, le=1.0)
    factor_fc_sf: float = Field(default=0.91, ge=0.5, le=1.0)
    ekr_motor: float = Field(default=0.40, ge=0.1, le=1.0)
    ekr_mobil: float = Field(default=1.00, ge=0.5, le=2.0)
    ekr_bus: float = Field(default=2.50, ge=1.0, le=6.0)
    ekr_truck: float = Field(default=8.90, ge=1.0, le=12.0)
    segment_mode: str = Field(default="khusus", pattern="^(khusus|umum_gunung|umum_bukit|umum_datar)$")
    citation: str = Field(default="SE Ditjen Bina Marga No. 21/SE/Db/2023")
    calculation_mode: str = Field(default="composite", pattern="^(composite|direct)$")
    p_bus_ks: float | None = Field(default=None, ge=0.0, le=1.0)
    p_bus_bb: float | None = Field(default=None, ge=0.0, le=1.0)
    p_truck_ks: float | None = Field(default=None, ge=0.0, le=1.0)
    p_truck_tb: float | None = Field(default=None, ge=0.0, le=1.0)
    subclass_ks_uphill: float | None = Field(default=None, ge=0.5, le=5.0)
    subclass_bb_uphill: float | None = Field(default=None, ge=0.5, le=8.0)
    subclass_tb_uphill: float | None = Field(default=None, ge=0.5, le=15.0)
    subclass_ks_downhill: float | None = Field(default=None, ge=0.5, le=5.0)
    subclass_bb_downhill: float | None = Field(default=None, ge=0.5, le=8.0)
    subclass_tb_downhill: float | None = Field(default=None, ge=0.5, le=10.0)
    estimated_transit_sec: int | None = Field(default=1485, ge=60, le=7200)
    persist: bool = True


# Alias untuk backwards compatibility
PKJICalibrateRequest = PKJIParams


@router.get("/pkji-params")
async def get_pkji_params():
    """Mengambil parameter aktif PKJI 2023 termasuk rincian sub-kelas dan komposisi."""
    from src.config import get_pkji_config, get_settings
    pkji = get_pkji_config()
    raw, _ = get_settings()
    transit_sec = int(raw.get("transit", {}).get("estimated_transit_sec", 1485))
    return {
        "base_capacity_c0": pkji.base_capacity_c0,
        "road_width_m": pkji.road_width_m,
        "factor_fc_w": pkji.factor_fc_w,
        "factor_fc_sp": pkji.factor_fc_sp,
        "factor_fc_sf": pkji.factor_fc_sf,
        "practical_capacity_c": pkji.practical_capacity_c,
        "segment_mode": getattr(pkji, "segment_mode", "khusus"),
        "citation": getattr(pkji, "citation", "SE Ditjen Bina Marga No. 21/SE/Db/2023"),
        "calculation_mode": getattr(pkji, "calculation_mode", "composite"),
        "ekr": pkji.ekr.model_dump(),
        "subclasses": pkji.subclasses.model_dump(),
        "composition_ratios": pkji.composition_ratios.model_dump(),
        "effective_ekr_uphill": pkji.calculate_composite_ekr("menanjak"),
        "effective_ekr_downhill": pkji.calculate_composite_ekr("menurun"),
        "los_thresholds": pkji.los_thresholds.model_dump(),
        "estimated_transit_sec": transit_sec,
        "estimated_transit_min": round(transit_sec / 60, 1),
    }


@router.post("/pkji-params")
async def update_pkji_params(payload: PKJIParams):
    """Menyimpan dan menerapkan parameter PKJI 2023 secara zero-downtime hot reload."""
    from src.config import persist_pkji_params, reload_settings
    try:
        if payload.persist:
            persist_pkji_params(
                base_capacity_c0=payload.base_capacity_c0,
                road_width_m=payload.road_width_m,
                factor_fc_w=payload.factor_fc_w,
                factor_fc_sp=payload.factor_fc_sp,
                factor_fc_sf=payload.factor_fc_sf,
                ekr_motor=payload.ekr_motor,
                ekr_mobil=payload.ekr_mobil,
                ekr_bus=payload.ekr_bus,
                ekr_truck=payload.ekr_truck,
                estimated_transit_sec=payload.estimated_transit_sec,
                segment_mode=payload.segment_mode,
                citation=payload.citation,
                calculation_mode=payload.calculation_mode,
                p_bus_ks=payload.p_bus_ks,
                p_bus_bb=payload.p_bus_bb,
                p_truck_ks=payload.p_truck_ks,
                p_truck_tb=payload.p_truck_tb,
                subclass_ks_uphill=payload.subclass_ks_uphill,
                subclass_bb_uphill=payload.subclass_bb_uphill,
                subclass_tb_uphill=payload.subclass_tb_uphill,
                subclass_ks_downhill=payload.subclass_ks_downhill,
                subclass_bb_downhill=payload.subclass_bb_downhill,
                subclass_tb_downhill=payload.subclass_tb_downhill,
            )
        else:
            reload_settings()

        # Siarkan snapshot terbaru ke seluruh dashboard yang terhubung
        snap = state.occupancy_manager.snapshot_to_dict()
        await state.broadcaster.broadcast(snap)

        return {
            "status": "success",
            "message": "Parameter PKJI 2023 berhasil diperbarui",
            "snapshot": snap,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Gagal memperbarui parameter: {exc}") from exc


class SimulateTrafficRequest(BaseModel):
    status: str = Field(default="macet", pattern="^(macet|padat|lancar)$")
    truck_count: int | None = None
    bus_count: int | None = None
    mobil_count: int | None = None
    motor_count: int | None = None
    fill_diurnal: bool = Field(default=True, description="Isi profil fluktuasi harian realistis dari 00:00 hingga jam lalu")


@router.post("/simulate-traffic")
async def simulate_traffic(payload: SimulateTrafficRequest = SimulateTrafficRequest()):
    """Menyuntikkan data dummy kendaraan untuk menguji status lalu lintas (LANCAR / PADAT / MACET)."""
    from datetime import datetime
    from src.storage.database import save_crossing
    target = payload.status.lower()

    if target == "macet":
        # Target DS >= 0.85 -> Q >= 2600 smp/jam -> 650 smp dalam rolling window 15 menit
        n_truck = payload.truck_count if payload.truck_count is not None else 65
        n_bus = payload.bus_count if payload.bus_count is not None else 25
        n_mobil = payload.mobil_count if payload.mobil_count is not None else 45
        n_motor = payload.motor_count if payload.motor_count is not None else 50
    elif target == "padat":
        # Target DS ~ 0.60 -> Q ~ 1760 smp/jam -> ~440 smp
        n_truck = payload.truck_count if payload.truck_count is not None else 35
        n_bus = payload.bus_count if payload.bus_count is not None else 15
        n_mobil = payload.mobil_count if payload.mobil_count is not None else 30
        n_motor = payload.motor_count if payload.motor_count is not None else 40
    else:  # lancar
        n_truck = payload.truck_count if payload.truck_count is not None else 5
        n_bus = payload.bus_count if payload.bus_count is not None else 2
        n_mobil = payload.mobil_count if payload.mobil_count is not None else 10
        n_motor = payload.motor_count if payload.motor_count is not None else 15

    # Isi riwayat jam-jam sebelumnya hari ini dengan profil diurnal alami jika diminta
    if payload.fill_diurnal:
        now_h = datetime.now().hour
        for h in range(now_h):
            if h <= 4:
                state.occupancy_manager._hourly_counts[h] = {"truck": 12, "bus": 4, "mobil": 15, "motor": 8}
            elif h <= 6:
                state.occupancy_manager._hourly_counts[h] = {"truck": 22, "bus": 8, "mobil": 35, "motor": 30}
            elif h <= 9:
                state.occupancy_manager._hourly_counts[h] = {"truck": 38, "bus": 18, "mobil": 75, "motor": 90}
            elif h <= 12:
                state.occupancy_manager._hourly_counts[h] = {"truck": 45, "bus": 20, "mobil": 80, "motor": 70}
            elif h <= 15:
                state.occupancy_manager._hourly_counts[h] = {"truck": 48, "bus": 22, "mobil": 85, "motor": 75}
            elif h <= 18:
                state.occupancy_manager._hourly_counts[h] = {"truck": 55, "bus": 24, "mobil": 90, "motor": 95}
            else:
                state.occupancy_manager._hourly_counts[h] = {"truck": 40, "bus": 15, "mobil": 50, "motor": 40}

    # Suntikkan ke occupancy manager dan database
    for _ in range(n_truck):
        state.occupancy_manager.register_entry("truck", gate="A", direction="menanjak")
        save_crossing("A", "in", "truck", 0.90)
    for _ in range(n_bus):
        state.occupancy_manager.register_entry("bus", gate="A", direction="menanjak")
        save_crossing("A", "in", "bus", 0.88)
    for _ in range(n_mobil):
        state.occupancy_manager.register_entry("mobil", gate="A", direction="menanjak")
        save_crossing("A", "in", "mobil", 0.85)
    for _ in range(n_motor):
        state.occupancy_manager.register_entry("motor", gate="A", direction="menanjak")
        save_crossing("A", "in", "motor", 0.80)

    snap = state.occupancy_manager.snapshot_to_dict()
    await state.broadcaster.broadcast(snap)

    return {
        "status": "success",
        "message": f"Data simulasi berhasil disuntikkan: Status {snap['status'].upper()} (DS: {snap['degree_of_saturation']}, LoS: {snap['los']})",
        "simulated_counts": {
            "target": target,
            "truck": n_truck,
            "bus": n_bus,
            "mobil": n_mobil,
            "motor": n_motor,
        },
        "snapshot": snap,
    }


async def _dev_mjpeg_generator(gate_id: str):
    gate_id = gate_id.upper()
    boundary = b"frame"
    from src.config import get_settings
    _, env = get_settings()

    is_edge = (gate_id in ("A", "B")) and state.is_gate_edge(gate_id, env)

    if is_edge:
        while True:
            import time
            node_info = state.edge_nodes.get(gate_id, {})
            last = node_info.get("last_seen")
            is_recent = (last is not None) and ((time.time() - last) <= 120.0)
            configured_url = getattr(env, f"gate_{gate_id.lower()}_edge_url", "")
            is_online = (node_info.get("status") == "online") or is_recent or bool(configured_url)
            edge_ip = configured_url or (
                f"http://{node_info.get('ip')}:8080" if node_info.get("ip") else ""
            )

            if is_online and edge_ip:
                try:
                    stream_url = f"{edge_ip.rstrip('/')}/stream/dev"
                    async with httpx.AsyncClient(timeout=5.0) as client:
                        async with client.stream("GET", stream_url) as resp:
                            if resp.status_code == 200:
                                async for chunk in resp.aiter_bytes():
                                    yield chunk
                                    state.edge_nodes[gate_id]["last_seen"] = time.time()
                                    state.edge_nodes[gate_id]["status"] = "online"
                            elif resp.status_code == 404:
                                # Fallback jika edge node belum diperbarui ke versi dual stream
                                async with client.stream("GET", f"{edge_ip.rstrip('/')}/stream") as resp_fallback:
                                    if resp_fallback.status_code == 200:
                                        async for chunk in resp_fallback.aiter_bytes():
                                            yield chunk
                                            state.edge_nodes[gate_id]["last_seen"] = time.time()
                                            state.edge_nodes[gate_id]["status"] = "online"
                except Exception:
                    pass

            # Saat Raspberry Pi offline, tunggu tanpa mengirim frame raster palsu (UI frontend menangani tampilan)
            await asyncio.sleep(0.5)

    else:
        # Mode lokal worker laptop
        while True:
            worker = state.detection_worker
            if worker is None:
                await asyncio.sleep(0.5)
                continue

            jpeg = worker.get_debug_jpeg(gate_id)
            if jpeg:
                yield (
                    b"--" + boundary + b"\r\n"
                    b"Content-Type: image/jpeg\r\n"
                    b"Content-Length: " + str(len(jpeg)).encode() + b"\r\n\r\n"
                    + jpeg + b"\r\n"
                )
            await asyncio.sleep(0.08)


@router.get("/stream/{gate_id}")
async def dev_stream(gate_id: str):
    """MJPEG stream dengan bounding box deteksi — khusus mode dev."""
    gate_id = gate_id.upper()
    return StreamingResponse(
        _dev_mjpeg_generator(gate_id),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


def _build_dev_gate_state(gate_id: str) -> dict:
    """Membangun snapshot state deteksi terkini baik untuk Edge Node maupun Worker lokal."""
    gate_id = gate_id.upper()
    from src.config import get_settings
    _, env = get_settings()

    is_edge = (gate_id in ("A", "B")) and state.is_gate_edge(gate_id, env)
    if is_edge:
        from src.config import get_gate_config
        gate_cfg = get_gate_config(gate_id)
        node = state.edge_nodes.get(gate_id, {})
        counts = node.get("counts", {})
        counts_in = node.get("counts_in", {"motor": 0, "mobil": 0, "bus": 0, "truck": 0})
        counts_out = node.get("counts_out", {"motor": 0, "mobil": 0, "bus": 0, "truck": 0})
        edge_cal = state.edge_calibrations.get(gate_id, {})
        classes_total = {
            c: counts_in.get(c, 0) + counts_out.get(c, 0)
            for c in ("motor", "mobil", "bus", "truck")
        }
        return {
            "mode": "edge",
            "gate_id": gate_id,
            "status": node.get("status", "offline"),
            "backend": node.get("backend", "Hailo-8L"),
            "inference_fps": node.get("fps", 0.0),
            "frame_width": node.get("frame_width", 2560),
            "frame_height": node.get("frame_height", 1440),
            "detection_count": node.get("detection_count", 0),
            "track_count": node.get("track_count", 0),
            "total_in": counts.get("in", sum(counts_in.values())),
            "total_out": counts.get("out", sum(counts_out.values())),
            "counts_in": counts_in,
            "counts_out": counts_out,
            "live_class_counts": classes_total,
            "buffer_count": node.get("buffer_count", 0),
            "ip": node.get("ip"),
            "tracks": [],
            "classes": classes_total,
            "counting_line": edge_cal.get("counting_line", gate_cfg.counting_line if gate_cfg else [0, 854, 2559, 854]),
            "entry_direction": edge_cal.get("entry_direction", gate_cfg.entry_direction if gate_cfg else "down"),
            "lane_divider": edge_cal.get("lane_divider", gate_cfg.lane_divider if gate_cfg else [1150, 0, 1150, 1439]),
            "inbound_side": edge_cal.get("inbound_side", gate_cfg.inbound_side if gate_cfg else "left"),
            "running": node.get("status") == "online",
        }

    worker = state.detection_worker
    if worker is None:
        return {"error": "Detection worker belum aktif"}
    return worker.get_debug_state(gate_id)


@router.get("/state/{gate_id}")
async def dev_state(gate_id: str):
    """State deteksi terkini untuk panel debug."""
    return _build_dev_gate_state(gate_id)


@router.post("/calibrate/{gate_id}")
async def calibrate_gate(gate_id: str, payload: CalibrateRequest):
    """Terapkan garis counting baru; opsional simpan ke settings.yaml."""
    gate_id = gate_id.upper()
    from src.config import get_settings
    _, env = get_settings()

    is_edge = (gate_id in ("A", "B")) and state.is_gate_edge(gate_id, env)

    if payload.entry_direction and payload.entry_direction not in ("up", "down"):
        raise HTTPException(status_code=400, detail="entry_direction harus up atau down")
    if payload.inbound_side and payload.inbound_side not in ("left", "right"):
        raise HTTPException(status_code=400, detail="inbound_side harus left atau right")

    if is_edge:
        from src.config import get_gate_config, persist_gate_calibration
        cfg = get_gate_config(gate_id)
        cur_line = payload.counting_line or (cfg.counting_line if cfg else [100, 400, 900, 400])
        cur_dir = payload.entry_direction or (cfg.entry_direction if cfg else "down")
        cur_divider = payload.lane_divider if payload.lane_divider is not None else (cfg.lane_divider if cfg else None)
        cur_inbound = payload.inbound_side or (cfg.inbound_side if cfg else "left")

        state.edge_calibrations[gate_id] = {
            "counting_line": cur_line,
            "entry_direction": cur_dir,
            "lane_divider": cur_divider,
            "inbound_side": cur_inbound,
        }

        if payload.persist:
            persist_gate_calibration(
                gate_id=gate_id,
                counting_line=cur_line,
                entry_direction=cur_dir,
                lane_divider=payload.lane_divider,
                inbound_side=payload.inbound_side,
            )
        return {
            "status": "ok",
            "gate_id": gate_id,
            "counting_line": cur_line,
            "entry_direction": cur_dir,
            "lane_divider": cur_divider,
            "inbound_side": cur_inbound,
            "persisted": payload.persist,
        }

    worker = state.detection_worker
    if worker is None:
        raise HTTPException(status_code=503, detail="Detection worker belum aktif")

    try:
        return worker.apply_calibration(
            gate_id=gate_id,
            counting_line=payload.counting_line,
            entry_direction=payload.entry_direction,
            lane_divider=payload.lane_divider,
            inbound_side=payload.inbound_side,
            persist=payload.persist,
            reset_counts=payload.reset_counts,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.websocket("/ws/{gate_id}")
async def dev_ws(websocket: WebSocket, gate_id: str):
    """WebSocket update deteksi real-time untuk halaman dev."""
    gate_id = gate_id.upper()
    await websocket.accept()
    from src.config import get_settings
    _, env = get_settings()

    is_edge = (gate_id in ("A", "B")) and state.is_gate_edge(gate_id, env)
    if is_edge:
        try:
            while True:
                data = _build_dev_gate_state(gate_id)
                await websocket.send_json(data)
                await asyncio.sleep(0.5)
        except WebSocketDisconnect:
            pass
        except Exception:
            pass
        return

    worker = state.detection_worker
    if worker is None:
        await websocket.close()
        return

    queue = await state.debug_broadcaster.subscribe(gate_id)
    try:
        initial = worker.get_debug_state(gate_id)
        if initial:
            await websocket.send_json(initial)
        while True:
            data = await queue.get()
            await websocket.send_json(data)
    except WebSocketDisconnect:
        state.debug_broadcaster.unsubscribe(gate_id, queue)
    except Exception:
        state.debug_broadcaster.unsubscribe(gate_id, queue)
