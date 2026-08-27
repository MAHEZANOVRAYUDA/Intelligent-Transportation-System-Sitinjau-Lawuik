"""Dev mode API routes."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from src.api import state

router = APIRouter(prefix="/api/dev", tags=["development"])


class CalibrateRequest(BaseModel):
    counting_line: list[int] | None = Field(default=None, min_length=4, max_length=4)
    entry_direction: str | None = None
    lane_divider: list[int] | None = Field(default=None, min_length=4, max_length=4)
    inbound_side: str | None = None
    persist: bool = False
    reset_counts: bool = True


async def _dev_mjpeg_generator(gate_id: str):
    boundary = b"frame"
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


@router.get("/state/{gate_id}")
async def dev_state(gate_id: str):
    """State deteksi terkini untuk panel debug."""
    gate_id = gate_id.upper()
    worker = state.detection_worker
    if worker is None:
        return {"error": "Detection worker belum aktif"}
    return worker.get_debug_state(gate_id)


@router.post("/calibrate/{gate_id}")
async def calibrate_gate(gate_id: str, payload: CalibrateRequest):
    """Terapkan garis counting baru; opsional simpan ke settings.yaml."""
    gate_id = gate_id.upper()
    worker = state.detection_worker
    if worker is None:
        raise HTTPException(status_code=503, detail="Detection worker belum aktif")

    if payload.entry_direction and payload.entry_direction not in ("up", "down"):
        raise HTTPException(status_code=400, detail="entry_direction harus up atau down")
    if payload.inbound_side and payload.inbound_side not in ("left", "right"):
        raise HTTPException(status_code=400, detail="inbound_side harus left atau right")

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
