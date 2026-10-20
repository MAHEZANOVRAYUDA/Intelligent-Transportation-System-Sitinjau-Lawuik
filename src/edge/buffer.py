"""Offline buffer SQLite untuk menjamin zero data loss saat jaringan putus di edge."""

from __future__ import annotations

import contextlib
import logging
import pathlib
import sqlite3
import threading
import time
from typing import Any, Generator

logger = logging.getLogger(__name__)


class EdgeBufferManager:
    """Manajer antrean lokal SQLite untuk penyimpanan data lalin saat koneksi offline."""

    def __init__(self, db_path: str | pathlib.Path = "offline_buffer.db"):
        self.db_path = pathlib.Path(db_path)
        self._lock = threading.Lock()
        self._init_db()

    @contextlib.contextmanager
    def _connection(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._lock, self._connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS antrean_lalin (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    gate_id TEXT NOT NULL,
                    arah TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    motor INTEGER NOT NULL DEFAULT 0,
                    mobil INTEGER NOT NULL DEFAULT 0,
                    bus INTEGER NOT NULL DEFAULT 0,
                    truk INTEGER NOT NULL DEFAULT 0,
                    interval_menit INTEGER NOT NULL DEFAULT 5,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL
                )
            """)
            conn.commit()

    def enqueue(
        self,
        gate_id: str,
        arah: str,
        timestamp: str,
        motor: int,
        mobil: int,
        bus: int,
        truk: int,
        interval_menit: int = 5,
    ) -> int:
        """Menambahkan rekaman lalu lintas ke antrean offline."""
        with self._lock, self._connection() as conn:
            cur = conn.execute(
                """
                INSERT INTO antrean_lalin (
                    gate_id, arah, timestamp, motor, mobil, bus, truk, interval_menit, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (gate_id, arah, timestamp, motor, mobil, bus, truk, interval_menit, time.time()),
            )
            conn.commit()
            record_id = int(cur.lastrowid or 0)
            logger.info("[BUFFER ENQUEUE] Tersimpan ke buffer lokal: ID %d (%s, %s)", record_id, gate_id, arah)
            return record_id

    def peek(self, limit: int = 50) -> list[dict[str, Any]]:
        """Melihat batch rekaman tertua yang belum berhasil terkirim."""
        with self._lock, self._connection() as conn:
            cur = conn.execute(
                """
                SELECT id, gate_id, arah, timestamp, motor, mobil, bus, truk, interval_menit, retry_count
                FROM antrean_lalin
                ORDER BY id ASC
                LIMIT ?
                """,
                (limit,),
            )
            return [dict(row) for row in cur.fetchall()]

    def dequeue(self, record_ids: list[int]) -> int:
        """Menghapus rekaman yang telah berhasil disinkronisasi ke server pusat."""
        if not record_ids:
            return 0
        placeholders = ",".join("?" for _ in record_ids)
        with self._lock, self._connection() as conn:
            cur = conn.execute(
                f"DELETE FROM antrean_lalin WHERE id IN ({placeholders})",
                record_ids,
            )
            conn.commit()
            deleted_count = cur.rowcount
            logger.info("[BUFFER DEQUEUE] Terhapus %d rekaman dari buffer lokal.", deleted_count)
            return deleted_count

    def increment_retry(self, record_ids: list[int]) -> None:
        """Menambah counter percobaan gagal pengiriman."""
        if not record_ids:
            return
        placeholders = ",".join("?" for _ in record_ids)
        with self._lock, self._connection() as conn:
            conn.execute(
                f"UPDATE antrean_lalin SET retry_count = retry_count + 1 WHERE id IN ({placeholders})",
                record_ids,
            )
            conn.commit()

    def count(self) -> int:
        """Menghitung total rekaman tertunda di buffer lokal."""
        with self._lock, self._connection() as conn:
            cur = conn.execute("SELECT COUNT(*) FROM antrean_lalin")
            row = cur.fetchone()
            return int(row[0]) if row else 0
