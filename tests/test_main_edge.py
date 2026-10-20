"""Unit tests untuk main_edge.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest

from main_edge import SitinjauEdgeRunner


def test_edge_runner_initialization():
    runner = SitinjauEdgeRunner(
        gate_id="A",
        rtsp_url="rtsp://mock-camera:554/live",
        server_url="http://mock-vps:8000",
        interval_menit=5,
        backend="auto",
    )
    assert runner.gate_id == "A"
    assert runner.rtsp_url == "rtsp://mock-camera:554/live"
    assert runner.server_url == "http://mock-vps:8000"
    assert runner.interval_menit == 5
    assert runner.counts_interval == {"motor": 0, "mobil": 0, "bus": 0, "truck": 0}


def test_edge_runner_dispatch():
    runner = SitinjauEdgeRunner(
        gate_id="A",
        rtsp_url="rtsp://mock-camera:554/live",
        server_url="http://mock-vps:8000",
        interval_menit=5,
        backend="auto",
    )
    runner.counts_interval = {"motor": 12, "mobil": 6, "bus": 1, "truck": 4}

    with patch.object(runner.sync_client, "send_or_buffer") as mock_send:
        mock_send.return_value = True
        runner._dispatch_interval_report()

        mock_send.assert_called_once()
        call_kwargs = mock_send.call_args[1]
        assert call_kwargs["arah"] == "MENANJAK"
        assert call_kwargs["motor"] == 12
        assert call_kwargs["mobil"] == 6
        assert call_kwargs["bus"] == 1
        assert call_kwargs["truk"] == 4
        assert call_kwargs["interval_menit"] == 5

        # Akumulator harus kembali di-reset
        assert runner.counts_interval == {"motor": 0, "mobil": 0, "bus": 0, "truck": 0}
