"""FastAPI application entry point."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

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
    if env.gate_b_rtsp_url:
        state.stream_registry.register(
            RTSPStreamManager(rtsp_url=env.gate_b_rtsp_url, gate_id="B")
        )

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
            snap = state.occupancy_manager.snapshot_to_dict()
            if state.detection_worker:
                snap["gate_counts"] = state.detection_worker.get_counter_stats()
                snap["live_class_counts"] = state.detection_worker.get_live_class_counts()
            snap["today_crossings"] = get_today_crossings()
            snap["streams"] = {
                gid: {
                    "state": sm.state.value,
                    "fps": round(sm.stats.fps_actual, 1),
                    "frames": sm.stats.frames_read,
                }
                for gid, sm in state.stream_registry.all().items()
            }
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

from src.api.routes.dev import calibrate_gate as _calibrate_gate

app.add_api_route(
    "/api/dev/calibrate/{gate_id}",
    _calibrate_gate,
    methods=["POST"],
    tags=["development"],
)

static_dir = ROOT_DIR / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    index = ROOT_DIR / "static" / "dashboard" / "index.html"
    if index.exists():
        return HTMLResponse(index.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Sitinjau Laut Monitoring</h1><p>Dashboard belum tersedia.</p>")


@app.get("/dev", response_class=HTMLResponse)
async def dev_dashboard():
    index = ROOT_DIR / "static" / "dev" / "index.html"
    if index.exists():
        return HTMLResponse(index.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Dev Dashboard</h1><p>File belum tersedia.</p>")


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "streams": {
            gid: sm.state.value for gid, sm in state.stream_registry.all().items()
        },
    }


@app.get("/api/monitoring/current")
async def current_monitoring():
    snap = state.occupancy_manager.snapshot_to_dict()
    snap["gate_counts"] = state.detection_worker.get_counter_stats() if state.detection_worker else {}
    snap["live_class_counts"] = (
        state.detection_worker.get_live_class_counts() if state.detection_worker else {}
    )
    snap["today_crossings"] = get_today_crossings()
    return snap


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
    return {"ok": True, "deleted": deleted}


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


@app.get("/api/stream/{gate_id}")
async def live_stream(gate_id: str):
    gate_id = gate_id.upper()
    stream = state.stream_registry.get(gate_id)
    if stream is None:
        return {"error": f"Gerbang {gate_id} tidak ditemukan atau belum dikonfigurasi"}

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
