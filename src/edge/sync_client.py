"""Klien sinkronisasi data edge ke server pusat dengan failover offline buffer."""

from __future__ import annotations

import logging
from typing import Any
import requests

from src.edge.buffer import EdgeBufferManager

logger = logging.getLogger(__name__)


class EdgeSyncClient:
    """Klien pengirim data lalu lintas dari Edge Node (RPi 5) ke Server Pusat FastAPI."""

    def __init__(
        self,
        server_url: str,
        gate_id: str,
        buffer_manager: EdgeBufferManager | None = None,
        timeout_sec: float = 5.0,
    ):
        self.server_url = server_url.rstrip("/")
        self.gate_id = gate_id
        self.buffer = buffer_manager or EdgeBufferManager()
        self.timeout_sec = timeout_sec

    def send_heartbeat(
        self,
        backend: str,
        fps: float,
        total_in: int = 0,
        total_out: int = 0,
        buffer_count: int = 0,
    ) -> bool:
        """Kirim sinyal heartbeat ringan ke server pusat."""
        payload = {
            "gate_id": self.gate_id,
            "backend": backend,
            "fps": fps,
            "total_in": total_in,
            "total_out": total_out,
            "buffer_count": buffer_count,
        }
        endpoint = f"{self.server_url}/api/edge/heartbeat"
        try:
            resp = requests.post(endpoint, json=payload, timeout=2.0)
            return resp.status_code == 200
        except Exception:
            return False

    def send_or_buffer(
        self,
        arah: str,
        timestamp: str,
        motor: int,
        mobil: int,
        bus: int,
        truk: int,
        interval_menit: int = 5,
    ) -> bool:
        """
        Kirim data ke server pusat. Jika koneksi gagal, simpan ke antrean offline buffer.
        """
        payload = {
            "gate_id": self.gate_id,
            "arah": arah,
            "timestamp": timestamp,
            "motor": motor,
            "mobil": mobil,
            "bus": bus,
            "truk": truk,
            "interval_menit": interval_menit,
        }

        endpoint = f"{self.server_url}/api/lapor-lalin"
        try:
            resp = requests.post(endpoint, json=payload, timeout=self.timeout_sec)
            if resp.status_code == 200:
                logger.info("[SYNC SUKSES] Data %s terkirim ke server pusat: %s", self.gate_id, resp.json())
                # Otomatis kuras data lama jika ada
                self.flush_pending_buffer()
                return True
            else:
                logger.warning("[SYNC GAGAL] Status code: %d, isi: %s", resp.status_code, resp.text)
                self.buffer.enqueue(
                    gate_id=self.gate_id,
                    arah=arah,
                    timestamp=timestamp,
                    motor=motor,
                    mobil=mobil,
                    bus=bus,
                    truk=truk,
                    interval_menit=interval_menit,
                )
                return False
        except Exception as e:
            logger.warning("[OFFLINE] Gangguan koneksi ke %s: %s. Menyimpan ke buffer lokal.", endpoint, e)
            self.buffer.enqueue(
                gate_id=self.gate_id,
                arah=arah,
                timestamp=timestamp,
                motor=motor,
                mobil=mobil,
                bus=bus,
                truk=truk,
                interval_menit=interval_menit,
            )
            return False

    def flush_pending_buffer(self, batch_size: int = 25) -> int:
        """
        Mengirimkan rekaman offline yang tertunda secara berurutan saat internet kembali online.
        """
        pending = self.buffer.peek(limit=batch_size)
        if not pending:
            return 0

        logger.info("[BUFFER FLUSH] Memproses %d rekaman tertunda...", len(pending))
        endpoint = f"{self.server_url}/api/lapor-lalin"
        success_ids: list[int] = []

        for record in pending:
            payload = {
                "gate_id": record["gate_id"],
                "arah": record["arah"],
                "timestamp": record["timestamp"],
                "motor": record["motor"],
                "mobil": record["mobil"],
                "bus": record["bus"],
                "truk": record["truk"],
                "interval_menit": record["interval_menit"],
            }
            try:
                resp = requests.post(endpoint, json=payload, timeout=self.timeout_sec)
                if resp.status_code == 200:
                    success_ids.append(record["id"])
                else:
                    logger.warning("[BUFFER FLUSH] Gagal kirim ID %d: %s", record["id"], resp.status_code)
                    break
            except Exception as e:
                logger.warning("[BUFFER FLUSH] Koneksi terputus saat flush ID %d: %s", record["id"], e)
                break

        if success_ids:
            self.buffer.dequeue(success_ids)
            logger.info("[BUFFER FLUSH] Berhasil sinkronisasi %d rekaman lama!", len(success_ids))

        return len(success_ids)
