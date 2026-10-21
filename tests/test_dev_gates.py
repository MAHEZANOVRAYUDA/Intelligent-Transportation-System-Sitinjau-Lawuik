"""Unit tests untuk multi-gate support (Gerbang A dan Gerbang B) pada /dev."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from src.api.main import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_dev_state_gate_a(client):
    """Memverifikasi endpoint /api/dev/state/A mengembalikan state valid."""
    res = client.get("/api/dev/state/A")
    assert res.status_code == 200
    data = res.json()
    assert "counting_line" in data
    assert len(data["counting_line"]) == 4
    assert "entry_direction" in data


def test_dev_state_gate_b(client):
    """Memverifikasi endpoint /api/dev/state/B mengembalikan state valid untuk Gerbang B."""
    res = client.get("/api/dev/state/B")
    assert res.status_code == 200
    data = res.json()
    assert "counting_line" in data
    assert len(data["counting_line"]) == 4
    assert data["frame_width"] == 2560
    assert data["frame_height"] == 1440
    assert "lane_divider" in data
    assert len(data["lane_divider"]) == 4
    assert "entry_direction" in data


def test_dev_calibrate_gate_b(client):
    """Memverifikasi kalibrasi garis pada Gerbang B."""
    payload = {
        "counting_line": [150, 420, 950, 420],
        "entry_direction": "down",
        "persist": False,
        "reset_counts": True,
    }
    res = client.post("/api/dev/calibrate/B", json=payload)
    assert res.status_code == 200
    resp_data = res.json()
    assert resp_data["gate_id"] == "B"
    assert resp_data["counting_line"] == [150, 420, 950, 420]

    # Cek kembali via get state
    state_res = client.get("/api/dev/state/B")
    assert state_res.status_code == 200
    assert state_res.json()["counting_line"] == [150, 420, 950, 420]


def test_dev_html_contains_gate_b():
    """Memverifikasi bahwa static/dev/index.html memiliki antarmuka switch Gerbang B."""
    from pathlib import Path
    html_path = Path("static/dev/index.html")
    assert html_path.exists()
    content = html_path.read_text(encoding="utf-8")

    assert "tab-gate-a" in content
    assert "tab-gate-b" in content
    assert "switchGate('B')" in content
    assert "active-gate-badge" in content
    assert "GATE_METADATA" in content
