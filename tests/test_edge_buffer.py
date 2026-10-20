"""Unit test untuk EdgeBufferManager dan EdgeSyncClient failover."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.edge.buffer import EdgeBufferManager
from src.edge.sync_client import EdgeSyncClient


@pytest.fixture
def temp_buffer():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_buffer.db"
        yield EdgeBufferManager(db_path=db_path)


def test_buffer_enqueue_and_count(temp_buffer: EdgeBufferManager):
    assert temp_buffer.count() == 0

    rec_id = temp_buffer.enqueue(
        gate_id="GERBANG_A",
        arah="MENANJAK",
        timestamp="2026-10-20T10:00:00",
        motor=10,
        mobil=5,
        bus=1,
        truk=2,
        interval_menit=5,
    )
    assert rec_id > 0
    assert temp_buffer.count() == 1


def test_buffer_peek_and_dequeue(temp_buffer: EdgeBufferManager):
    temp_buffer.enqueue("GERBANG_A", "MENANJAK", "2026-10-20T10:00:00", 1, 2, 0, 1)
    temp_buffer.enqueue("GERBANG_A", "MENANJAK", "2026-10-20T10:05:00", 3, 4, 1, 0)

    records = temp_buffer.peek(limit=10)
    assert len(records) == 2
    assert records[0]["motor"] == 1
    assert records[1]["motor"] == 3

    # Dequeue first record
    deleted = temp_buffer.dequeue([records[0]["id"]])
    assert deleted == 1
    assert temp_buffer.count() == 1

    remaining = temp_buffer.peek()
    assert remaining[0]["id"] == records[1]["id"]


def test_sync_client_success(temp_buffer: EdgeBufferManager):
    client = EdgeSyncClient(
        server_url="http://mock-server:8000",
        gate_id="GERBANG_A",
        buffer_manager=temp_buffer,
    )

    with patch("requests.post") as mock_post:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "sukses"}
        mock_post.return_value = mock_response

        success = client.send_or_buffer(
            arah="MENANJAK",
            timestamp="2026-10-20T12:00:00",
            motor=5,
            mobil=10,
            bus=2,
            truk=3,
        )

        assert success is True
        assert temp_buffer.count() == 0
        mock_post.assert_called_once()


def test_sync_client_offline_fallback(temp_buffer: EdgeBufferManager):
    client = EdgeSyncClient(
        server_url="http://mock-server:8000",
        gate_id="GERBANG_A",
        buffer_manager=temp_buffer,
    )

    with patch("requests.post", side_effect=Exception("Connection refused")):
        success = client.send_or_buffer(
            arah="MENANJAK",
            timestamp="2026-10-20T12:00:00",
            motor=5,
            mobil=10,
            bus=2,
            truk=3,
        )

        assert success is False
        assert temp_buffer.count() == 1

        buffered = temp_buffer.peek()[0]
        assert buffered["gate_id"] == "GERBANG_A"
        assert buffered["motor"] == 5


def test_sync_client_flush_recovery(temp_buffer: EdgeBufferManager):
    # Enqueue 2 items manually
    temp_buffer.enqueue("GERBANG_A", "MENANJAK", "2026-10-20T12:00:00", 5, 2, 0, 1)
    temp_buffer.enqueue("GERBANG_A", "MENANJAK", "2026-10-20T12:05:00", 3, 1, 1, 0)
    assert temp_buffer.count() == 2

    client = EdgeSyncClient(
        server_url="http://mock-server:8000",
        gate_id="GERBANG_A",
        buffer_manager=temp_buffer,
    )

    with patch("requests.post") as mock_post:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        flushed = client.flush_pending_buffer(batch_size=10)
        assert flushed == 2
        assert temp_buffer.count() == 0
