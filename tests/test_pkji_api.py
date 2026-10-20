"""Pengujian API PKJI 2023 dan validasi parameter telemetri."""

import pytest
from fastapi.testclient import TestClient
from src.api.main import app
from src.config import get_pkji_config


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_get_pkji_params(client):
    res = client.get("/api/dev/pkji-params")
    assert res.status_code == 200
    data = res.json()
    assert "base_capacity_c0" in data
    assert "practical_capacity_c" in data
    assert "ekr" in data
    assert "mobil" in data["ekr"]
    assert "truck" in data["ekr"]
    assert data["base_capacity_c0"] == 3550.0
    assert data["practical_capacity_c"] == 2939.76
    assert data["ekr"]["bus"] == 2.50
    assert data["ekr"]["truck"] == 8.90
    assert data.get("segment_mode") == "khusus"
    assert "SE Ditjen Bina Marga No. 21/SE/Db/2023" in data.get("citation", "")
    assert "los_thresholds" in data


def test_post_pkji_params_temporary(client):
    # Uji update parameter tanpa persist ke file (persist=False)
    payload = {
        "base_capacity_c0": 3000.0,
        "road_width_m": 7.0,
        "factor_fc_w": 1.0,
        "factor_fc_sp": 1.0,
        "factor_fc_sf": 0.90,
        "ekr_motor": 0.40,
        "ekr_mobil": 1.00,
        "ekr_bus": 1.60,
        "ekr_truck": 3.50,
        "segment_mode": "umum_bukit",
        "citation": "SE Ditjen Bina Marga No. 21/SE/Db/2023",
        "estimated_transit_sec": 1500,
        "persist": False,
    }
    res = client.post("/api/dev/pkji-params", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert "snapshot" in data


def test_linear_interpolation_fc_w():
    from src.analytics.density import interpolate_fc_w
    # Lebar jalur efektif 6.5 m harus terinterpolasi ke 0.91
    assert interpolate_fc_w(6.5) == 0.91
    assert interpolate_fc_w(6.0) == 0.82
    assert interpolate_fc_w(7.0) == 1.00
    assert interpolate_fc_w(5.0) == 0.69
    assert interpolate_fc_w(8.0) == 1.08


def test_directional_ekr():
    from src.analytics.density import get_ekr
    # Arah menanjak (ke Solok)
    assert get_ekr("truck", "menanjak") == 8.90
    assert get_ekr("bus", "menanjak") == 2.50
    assert get_ekr("mobil", "menanjak") == 1.00
    assert get_ekr("motor", "menanjak") == 0.40

    # Arah menurun (ke Padang)
    assert get_ekr("truck", "menurun") == 2.50
    assert get_ekr("bus", "menurun") == 1.60
    assert get_ekr("mobil", "menurun") == 1.00
    assert get_ekr("motor", "menurun") == 0.40


def test_monitoring_current_pkji_fields(client):
    res = client.get("/api/monitoring/current")
    assert res.status_code == 200
    snap = res.json()
    assert "volume_q_smp_jam" in snap
    assert "capacity_c_smp_jam" in snap
    assert snap["capacity_c_smp_jam"] == 2939.76
    assert "degree_of_saturation" in snap
    assert "los" in snap
    assert snap["los"] in ["A", "B", "C", "D", "E", "F"]
    assert "status" in snap
    assert snap["status"] in ["lancar", "padat", "macet"]
    assert "human_message" in snap
    assert "hourly_trend" in snap
    assert len(snap["hourly_trend"]) == 24
    first_hour = snap["hourly_trend"][0]
    assert "hour" in first_hour
    assert "volume_smp" in first_hour
    assert "capacity_smp" in first_hour
    assert first_hour["capacity_smp"] == 2939.76
    assert "degree_of_saturation" in first_hour
    assert "los" in first_hour
    assert "composite_meta" in snap
    assert snap["composite_meta"]["calculation_mode"] in ["composite", "direct"]
    assert "effective_ekr_uphill" in snap["composite_meta"]
    assert "effective_ekr_downhill" in snap["composite_meta"]


def test_composite_expected_emp_calculation():
    """Uji matematis formulasi Composite Expected EMP (E[emp]) PKJI 2023."""
    from src.config import PKJIConfig, PKJISubclassesConfig, PKJISubclassWeights, PKJICompositionConfig

    cfg = PKJIConfig(
        calculation_mode="composite",
        subclasses=PKJISubclassesConfig(
            uphill=PKJISubclassWeights(ks=1.50, bb=2.50, tb=8.90),
            downhill=PKJISubclassWeights(ks=1.20, bb=1.60, tb=2.50),
        ),
        composition_ratios=PKJICompositionConfig(
            p_bus_ks=0.70,
            p_bus_bb=0.30,
            p_truck_ks=0.45,
            p_truck_tb=0.55,
        ),
    )

    uphill = cfg.calculate_composite_ekr("menanjak")
    # E[emp_bus] = 0.70 * 1.50 + 0.30 * 2.50 = 1.05 + 0.75 = 1.80
    assert uphill["bus"] == 1.80
    # E[emp_truck] = 0.45 * 1.50 + 0.55 * 8.90 = 0.675 + 4.895 = 5.57
    assert uphill["truck"] == 5.57
    assert uphill["mobil"] == 1.00
    assert uphill["motor"] == 0.40

    downhill = cfg.calculate_composite_ekr("menurun")
    # Downhill bus: 0.70 * 1.20 + 0.30 * 1.60 = 0.84 + 0.48 = 1.32
    assert downhill["bus"] == 1.32
    # Downhill truck: 0.45 * 1.20 + 0.55 * 2.50 = 0.54 + 1.375 = 1.915 -> 1.92
    assert downhill["truck"] == 1.92


def test_lapor_lalin_endpoint(client):
    payload = {
        "gate_id": "GERBANG_A_PADANG_BESI",
        "arah": "MENANJAK",
        "timestamp": "2026-10-20T10:00:00",
        "motor": 10,
        "mobil": 5,
        "bus": 2,
        "truk": 3,
        "interval_menit": 5,
    }
    res = client.post("/api/lapor-lalin", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "sukses"
    assert data["gate_id"] == "GERBANG_A_PADANG_BESI"
    assert "volume_smp_jam" in data
    assert "derajat_kejenuhan_ds" in data
    assert "keputusan_pakar" in data
    assert data["volume_smp_jam"] > 0
    assert data["derajat_kejenuhan_ds"] > 0


