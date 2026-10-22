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


def test_edge_runner_web_stream_init():
    runner = SitinjauEdgeRunner(
        gate_id="B",
        web_stream=True,
        web_port=8081,
    )
    assert runner.gate_id == "B"
    assert runner.web_stream is True
    assert runner.web_port == 8081
    assert runner.stream_holder is not None


def test_edge_stream_holder():
    from main_edge import EdgeStreamHolder

    holder = EdgeStreamHolder()
    assert holder.get_frame() is None
    assert holder.get_metadata() == {}

    dummy_dev_jpeg = b"\xff\xd8\xff\xe0dummy_dev_jpeg_bytes"
    dummy_clean_jpeg = b"\xff\xd8\xff\xe0dummy_clean_jpeg_bytes"
    meta = {"fps": 28.5, "gate": "B", "counts_in": 10, "counts_out": 5}
    
    # Test dual stream: dev mode vs clean mode
    holder.update(annotated_jpeg=dummy_dev_jpeg, metadata=meta, clean_jpeg=dummy_clean_jpeg)

    assert holder.get_frame(mode="clean") == dummy_clean_jpeg
    assert holder.get_frame(mode="dev") == dummy_dev_jpeg
    assert holder.get_metadata() == meta


def test_edge_sync_client_heartbeat():
    from src.edge.sync_client import EdgeSyncClient

    client = EdgeSyncClient(server_url="http://mock-server:8000", gate_id="GERBANG_B")

    with patch("requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200)

        success = client.send_heartbeat(
            backend="hailo",
            fps=30.0,
            total_in=15,
            total_out=12,
            counts_in={"motor": 2, "mobil": 10, "bus": 1, "truck": 2},
            counts_out={"motor": 1, "mobil": 8, "bus": 1, "truck": 2},
            buffer_count=0,
            detection_count=3,
            track_count=2,
        )
        assert success is True
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert "/api/edge/heartbeat" in args[0]
        assert kwargs["json"]["gate_id"] == "GERBANG_B"
        assert kwargs["json"]["backend"] == "hailo"
        assert kwargs["json"]["fps"] == 30.0
        assert kwargs["json"]["counts_in"]["mobil"] == 10
        assert kwargs["json"]["counts_out"]["mobil"] == 8
        assert kwargs["json"]["detection_count"] == 3
        assert kwargs["json"]["track_count"] == 2


def test_edge_api_endpoints():
    from fastapi.testclient import TestClient
    from src.api.main import app

    with TestClient(app) as client:
        # Kirim heartbeat dari Gerbang B dengan rincian kelas
        hb_resp = client.post(
            "/api/edge/heartbeat",
            json={
                "gate_id": "B",
                "backend": "hailo",
                "fps": 28.5,
                "total_in": 12,
                "total_out": 8,
                "counts_in": {"motor": 2, "mobil": 8, "bus": 1, "truck": 1},
                "counts_out": {"motor": 1, "mobil": 5, "bus": 1, "truck": 1},
                "buffer_count": 0,
                "detection_count": 4,
                "track_count": 3,
            },
        )
        assert hb_resp.status_code == 200
        assert hb_resp.json()["status"] == "ok"

        # Cek status edge
        status_resp = client.get("/api/edge/status")
        assert status_resp.status_code == 200
        status_data = status_resp.json()
        assert "B" in status_data
        assert status_data["B"]["status"] == "online"
        assert status_data["B"]["backend"] == "hailo"
        assert status_data["B"]["fps"] == 28.5
        assert status_data["B"]["counts"]["in"] == 12
        assert status_data["B"]["counts"]["out"] == 8
        assert status_data["B"]["counts_in"]["mobil"] == 8
        assert status_data["B"]["counts_out"]["mobil"] == 5
        assert status_data["B"]["detection_count"] == 4
        assert status_data["B"]["track_count"] == 3

        # Cek dev state Gerbang B
        dev_resp = client.get("/api/dev/state/B")
        assert dev_resp.status_code == 200
        dev_data = dev_resp.json()
        assert dev_data["mode"] == "edge"
        assert dev_data["counts_in"]["mobil"] == 8
        assert dev_data["counts_out"]["mobil"] == 5
        assert dev_data["classes"]["mobil"] == 13


def test_edge_delta_ingestion_and_snapshot_merge():
    from fastapi.testclient import TestClient
    from src.api.main import app

    with TestClient(app) as client:
        # Kirim heartbeat Gerbang A dengan 3 mobil masuk dan 1 truk masuk
        resp = client.post(
            "/api/edge/heartbeat",
            json={
                "gate_id": "A",
                "backend": "hailo",
                "fps": 25.0,
                "total_in": 4,
                "total_out": 0,
                "counts_in": {"motor": 0, "mobil": 3, "bus": 0, "truck": 1},
                "counts_out": {"motor": 0, "mobil": 0, "bus": 0, "truck": 0},
                "buffer_count": 0,
                "detection_count": 2,
                "track_count": 2,
            },
        )
        assert resp.status_code == 200

        # Verifikasi snapshot monitoring
        snap_resp = client.get("/api/monitoring/current")
        assert snap_resp.status_code == 200
        snap_data = snap_resp.json()

        # 1. gate_counts harus terisi data Gerbang A
        assert "A" in snap_data["gate_counts"]
        assert snap_data["gate_counts"]["A"]["in"]["mobil"] == 3
        assert snap_data["gate_counts"]["A"]["in"]["truck"] == 1

        # 2. today_crossings database harus bertambah
        today = snap_data["today_crossings"]
        assert today["in"]["mobil"] >= 3
        assert today["in"]["truck"] >= 1

        # 3. volume smp/jam harus terhitung aktif
        assert snap_data["volume_q_smp_jam"] > 0
