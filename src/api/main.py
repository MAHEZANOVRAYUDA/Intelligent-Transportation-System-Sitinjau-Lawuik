"""FastAPI application entry point."""

from __future__ import annotations

import asyncio
import logging
import time
import psutil
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.api import state
from src.api.routes.dev import router as dev_router
from src.capture.stream_manager import RTSPStreamManager
from src.config import ensure_directories, get_gate_config, get_settings, get_stream_config
from src.storage.database import clear_all_records, get_recent_snapshots, get_today_crossings, init_db
from src.worker.detection_worker import DetectionWorker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).resolve().parent.parent.parent


def _on_monitoring_update(data: dict) -> None:
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.run_coroutine_threadsafe(state.broadcaster.broadcast(data), loop)
    except RuntimeError:
        state.broadcaster.set_latest(data)


def _on_debug_update(gate_id: str, data: dict) -> None:
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.run_coroutine_threadsafe(state.debug_broadcaster.broadcast(gate_id, data), loop)
    except RuntimeError:
        pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_directories()
    init_db()

    raw, env = get_settings()

    if env.gate_a_rtsp_url:
        state.stream_registry.register(
            RTSPStreamManager(rtsp_url=env.gate_a_rtsp_url, gate_id="A")
        )
    # Gerbang B hanya didaftarkan ke worker laptop jika bukan mode murni 'edge'
    is_edge_b = getattr(env, "gate_b_mode", "auto").lower() == "edge"
    if env.gate_b_rtsp_url and not is_edge_b:
        state.stream_registry.register(
            RTSPStreamManager(rtsp_url=env.gate_b_rtsp_url, gate_id="B")
        )
    elif is_edge_b:
        logger.info("Gerbang B dikonfigurasi sebagai EDGE NODE (Raspberry Pi 5) — Worker deteksi lokal laptop untuk Gerbang B dinonaktifkan.")

    state.stream_registry.start_all()

    state.detection_worker = DetectionWorker(
        stream_registry=state.stream_registry,
        occupancy=state.occupancy_manager,
        on_update=_on_monitoring_update,
        on_debug_update=_on_debug_update,
    )
    state.detection_worker.start()

    async def periodic_broadcast():
        while True:
            snap = _build_current_snapshot()
            await state.broadcaster.broadcast(snap)
            await asyncio.sleep(1)

    task = asyncio.create_task(periodic_broadcast())

    logger.info("Sitinjau Laut monitoring system started")
    yield

    task.cancel()
    if state.detection_worker:
        state.detection_worker.stop()
    state.stream_registry.stop_all()
    logger.info("System shutdown complete")


app = FastAPI(
    title="Sitinjau Laut Traffic Monitoring",
    description="Sistem monitoring lalu lintas Jalan Sitinjau Laut — Dishub Sumbar",
    version="0.1.0",
    lifespan=lifespan,
)

raw_cfg, _ = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=raw_cfg.get("api", {}).get("cors_origins", ["*"]),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(dev_router)

static_dir = ROOT_DIR / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    index = ROOT_DIR / "static" / "dashboard" / "index.html"
    if index.exists():
        response = HTMLResponse(index.read_text(encoding="utf-8"))
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response
    return HTMLResponse("<h1>Sitinjau Laut Monitoring</h1><p>Dashboard belum tersedia.</p>")


@app.get("/gerbang", response_class=HTMLResponse)
@app.get("/kamera", response_class=HTMLResponse)
async def gerbang_dashboard():
    gerbang_file = ROOT_DIR / "static" / "dashboard" / "gerbang.html"
    if gerbang_file.exists():
        response = HTMLResponse(gerbang_file.read_text(encoding="utf-8"))
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response
    return HTMLResponse("<h1>Kamera Gerbang</h1><p>File belum tersedia.</p>")


@app.get("/dev", response_class=HTMLResponse)
async def dev_dashboard():
    index = ROOT_DIR / "static" / "dev" / "index.html"
    if index.exists():
        response = HTMLResponse(index.read_text(encoding="utf-8"))
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response
    return HTMLResponse("<h1>Dev Dashboard</h1><p>File belum tersedia.</p>")


def get_edge_nodes_status() -> dict:
    now = time.time()
    result = {}
    for gid, node in state.edge_nodes.items():
        last = node.get("last_seen")
        is_online = (last is not None) and ((now - last) <= 60.0)
        result[gid] = {
            **node,
            "status": "online" if is_online else "offline",
            "seconds_since_last_seen": round(now - last, 1) if last else None,
        }
    return result


def _build_current_snapshot() -> dict:
    snap = state.occupancy_manager.snapshot_to_dict()
    if state.detection_worker:
        snap["gate_counts"] = state.detection_worker.get_counter_stats()
        snap["live_class_counts"] = state.detection_worker.get_live_class_counts()
    else:
        snap["gate_counts"] = {}
        snap["live_class_counts"] = {}
    snap["today_crossings"] = get_today_crossings()
    snap["streams"] = state.stream_registry.get_status_dict()
    snap["edge_nodes"] = get_edge_nodes_status()

    # Sinkronisasi status stream Gerbang B dari Edge Node jika mode edge aktif
    _, env = get_settings()
    if getattr(env, "gate_b_mode", "auto").lower() == "edge":
        edge_b = snap["edge_nodes"].get("B", {})
        is_edge_online = edge_b.get("status") == "online"
        snap["streams"]["B"] = {
            "gate_id": "B",
            "state": "live" if is_edge_online else "offline",
            "configured": True,
            "fps": edge_b.get("fps", 0.0),
            "is_live": is_edge_online,
            "width": edge_b.get("frame_width", 2560),
            "height": edge_b.get("frame_height", 1440),
            "error_message": None if is_edge_online else "Edge Node Offline",
        }
    try:
        snap["hardware"] = {
            "cpu_percent": psutil.cpu_percent(interval=None),
            "ram_percent": psutil.virtual_memory().percent,
        }
    except Exception:
        snap["hardware"] = {"cpu_percent": 0.0, "ram_percent": 0.0}
    return snap


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "streams": state.stream_registry.get_status_dict(),
    }


@app.get("/api/monitoring/current")
async def current_monitoring():
    return _build_current_snapshot()


@app.get("/api/monitoring/history")
async def monitoring_history(limit: int = 60):
    return {"snapshots": get_recent_snapshots(limit)}


@app.post("/api/monitoring/reset")
async def reset_monitoring():
    """Kosongkan database dan hitungan runtime (koridor, IN/OUT sesi)."""
    deleted = clear_all_records()
    if state.detection_worker:
        state.detection_worker.reset_runtime()
    else:
        state.occupancy_manager.reset()
    logger.info("Data monitoring direset: %s", deleted)
    snap = _build_current_snapshot()
    await state.broadcaster.broadcast(snap)
    return {"ok": True, "deleted": deleted, "snapshot": snap}


@app.get("/api/road/info")
async def road_info():
    raw, _ = get_settings()
    return {
        "name": "Jalan Sitinjau Laut (Gerbang A → B)",
        "length_km": raw["road"]["length_km"],
        "capacity_meter_lajur": raw["road"]["total_capacity_meter_lajur"],
        "thresholds": raw["traffic_status"],
        "vehicles": raw["vehicles"],
        "gates": {
            gid: get_gate_config(gid).model_dump() if get_gate_config(gid) else None
            for gid in ["A", "B"]
        },
    }


async def _mjpeg_generator(gate_id: str):
    """Generator MJPEG stream — frame bersih tanpa bounding box."""
    cfg = get_stream_config()
    stream = state.stream_registry.get(gate_id)
    if stream is None:
        return

    boundary = b"frame"
    interval = 1.0 / max(cfg.fps, 1)

    while True:
        jpeg = stream.get_frame_for_stream(cfg.output_width, cfg.output_height)
        if jpeg:
            yield (
                b"--" + boundary + b"\r\n"
                b"Content-Type: image/jpeg\r\n"
                b"Content-Length: " + str(len(jpeg)).encode() + b"\r\n\r\n"
                + jpeg + b"\r\n"
            )
        await asyncio.sleep(interval)


async def _proxy_edge_stream(gate_id: str = "B"):
    """Proxy streaming MJPEG langsung dari unit Edge Node (Raspberry Pi 5)."""
    import httpx
    from src.config import get_settings
    _, env = get_settings()

    while True:
        node_info = state.edge_nodes.get(gate_id, {})
        is_online = node_info.get("status") == "online"
        edge_ip = getattr(env, "gate_b_edge_url", "") or (
            f"http://{node_info.get('ip')}:8080" if node_info.get("ip") else ""
        )

        if is_online and edge_ip:
            try:
                stream_url = f"{edge_ip.rstrip('/')}/stream"
                async with httpx.AsyncClient(timeout=4.0) as client:
                    async with client.stream("GET", stream_url) as resp:
                        if resp.status_code == 200:
                            async for chunk in resp.aiter_bytes():
                                yield chunk
                                if state.edge_nodes.get(gate_id, {}).get("status") != "online":
                                    break
            except Exception:
                pass

        await asyncio.sleep(0.5)


@app.get("/api/stream/{gate_id}")
async def live_stream(gate_id: str):
    gate_id = gate_id.upper()
    _, env = get_settings()
    is_edge_b = (gate_id == "B") and (getattr(env, "gate_b_mode", "auto").lower() == "edge")

    if is_edge_b:
        return StreamingResponse(
            _proxy_edge_stream("B"),
            media_type="multipart/x-mixed-replace; boundary=frame",
        )

    stream = state.stream_registry.get(gate_id)
    if stream is None:
        raise HTTPException(
            status_code=404,
            detail=f"Gerbang {gate_id} tidak ditemukan atau belum dikonfigurasi",
        )

    return StreamingResponse(
        _mjpeg_generator(gate_id),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@app.websocket("/ws/monitoring")
async def ws_monitoring(websocket: WebSocket):
    await websocket.accept()
    queue = await state.broadcaster.subscribe()
    try:
        while True:
            data = await queue.get()
            await websocket.send_json(data)
    except WebSocketDisconnect:
        state.broadcaster.unsubscribe(queue)
    except Exception:
        state.broadcaster.unsubscribe(queue)


class PayloadGerbang(BaseModel):
    gate_id: str
    arah: str
    timestamp: str
    motor: int = 0
    mobil: int = 0
    bus: int = 0
    truk: int = 0
    interval_menit: int = 5


@app.post("/api/lapor-lalin")
async def terima_lapor_lalin(payload: PayloadGerbang, request: Request):
    """
    Endpoint Ingestion data lalu lintas dari Edge Node (Raspberry Pi 5 + Hailo-8L).
    Menerima agregasi interval (default 5 menit) dan memproses sesuai standar PKJI 2023.
    """
    from src.config import get_pkji_config
    pkji = get_pkji_config()
    kapasitas_jalan = float(pkji.practical_capacity_c)

    # Update status Edge Node pada server pusat
    gid = payload.gate_id.upper().replace("GERBANG_", "")
    client_ip = request.client.host if request.client else None
    if gid in state.edge_nodes:
        state.edge_nodes[gid]["last_seen"] = time.time()
        state.edge_nodes[gid]["status"] = "online"
        if client_ip:
            state.edge_nodes[gid]["ip"] = client_ip

    # Konversi bobot EKR/EMP sesuai arah
    is_naik = payload.arah.lower() in ("menanjak", "in", "up", "padang_to_solok")
    if is_naik:
        emp_motor = float(pkji.ekr.motor)
        emp_mobil = float(pkji.ekr.mobil)
        emp_bus = float(pkji.ekr.bus)
        emp_truk = float(pkji.ekr.truck)
    else:
        emp_motor = float(pkji.ekr.motor)
        emp_mobil = float(pkji.ekr.mobil)
        emp_bus = float(pkji.subclasses.downhill.bb)
        emp_truk = float(pkji.subclasses.downhill.tb)

    interval = max(1, payload.interval_menit)
    pengali_jam = 60.0 / interval
    q_smp_interval = (
        (payload.motor * emp_motor)
        + (payload.mobil * emp_mobil)
        + (payload.bus * emp_bus)
        + (payload.truk * emp_truk)
    )
    volume_q_jam = round(q_smp_interval * pengali_jam, 2)
    ds = round(volume_q_jam / max(kapasitas_jalan, 1.0), 3)

    if ds < 0.60:
        status = "ARUS LANCAR"
    elif ds < 0.80:
        status = "ARUS STABIL / RAMAI"
    elif ds < 0.95:
        status = "ARUS TIDAK STABIL / RAWAN MACET"
    else:
        status = "MACET / ARUS JENUH"

    logger.info(
        "[LAPOR-LALIN INGEST] %s (%s) -> Q=%.1f smp/jam, C=%.1f, DS=%.3f, Status=%s",
        payload.gate_id,
        payload.arah,
        volume_q_jam,
        kapasitas_jalan,
        ds,
        status,
    )

    return {
        "status": "sukses",
        "gate_id": payload.gate_id,
        "arah": payload.arah,
        "volume_smp_jam": volume_q_jam,
        "kapasitas_jalan": kapasitas_jalan,
        "derajat_kejenuhan_ds": ds,
        "keputusan_pakar": status,
    }


class EdgeHeartbeatPayload(BaseModel):
    gate_id: str
    backend: str = "hailo"
    fps: float = 0.0
    buffer_count: int = 0
    total_in: int = 0
    total_out: int = 0
    frame_width: int = 2560
    frame_height: int = 1440
    timestamp: str | None = None


@app.post("/api/edge/heartbeat")
async def edge_heartbeat(payload: EdgeHeartbeatPayload, request: Request):
    """Menerima sinyal detak jantung (heartbeat) & status performa NPU dari Edge Node."""
    gid = payload.gate_id.upper().replace("GERBANG_", "")
    client_ip = request.client.host if request.client else None
    if gid in state.edge_nodes:
        state.edge_nodes[gid].update({
            "status": "online",
            "last_seen": time.time(),
            "backend": payload.backend,
            "fps": round(payload.fps, 1),
            "buffer_count": payload.buffer_count,
            "counts": {"in": payload.total_in, "out": payload.total_out},
            "frame_width": payload.frame_width,
            "frame_height": payload.frame_height,
            "ip": client_ip,
        })
    return {"status": "ok", "gate_id": gid}


@app.get("/api/edge/status")
async def edge_status():
    """Mengembalikan status konektivitas Edge Node Raspberry Pi 5 di lapangan."""
    return get_edge_nodes_status()

