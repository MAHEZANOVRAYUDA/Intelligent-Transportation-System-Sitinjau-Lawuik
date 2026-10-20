"""Tes occupancy koridor & kalkulasi PKJI 2023."""

from src.analytics.density import LoSLevel, RoadOccupancyManager, TrafficLevel


def test_enter_then_exit_updates_on_road():
    occ = RoadOccupancyManager()
    occ.set_dual_gate_mode(True)
    for _ in range(5):
        occ.register_entry("mobil", gate="A")
    assert occ.snapshot_to_dict()["on_road"]["mobil"] == 5

    occ.register_exit("mobil", gate="A")
    snap = occ.snapshot_to_dict()
    assert snap["on_road"]["mobil"] == 4
    assert snap["on_road_total"] == 4


def test_reset_clears_corridor():
    occ = RoadOccupancyManager()
    occ.set_dual_gate_mode(True)
    occ.register_entry("motor", gate="A")
    occ.reset()
    snap = occ.snapshot_to_dict()
    assert snap["on_road_total"] == 0
    assert snap["on_road"]["motor"] == 0


def test_pkji_ekr_and_degree_of_saturation():
    occ = RoadOccupancyManager()
    occ.set_dual_gate_mode(True)

    # Masukkan 10 mobil (1.0 smp) dan 2 truk (8.9 smp di tanjakan)
    for _ in range(10):
        occ.register_entry("mobil", gate="A")
    for _ in range(2):
        occ.register_entry("truck", gate="A")

    snap = occ.snapshot_to_dict()
    # On road smp = 10 * 1.0 + 2 * 8.9 = 27.8 smp
    assert snap["on_road_smp"] == 27.8
    assert snap["capacity_c_smp_jam"] == 2939.76
    assert "degree_of_saturation" in snap
    assert "los" in snap
    assert snap["los"] in ["A", "B", "C", "D", "E", "F"]
    assert "hourly_trend" in snap
    assert len(snap["hourly_trend"]) == 24


def test_register_exit_always_increments_counts_out_even_when_on_road_empty():
    """Memastikan kendaraan keluar (turun) selalu tercatat di counter dan event meskipun antrean kosong."""
    occ = RoadOccupancyManager()
    occ.reset()

    # Pastikan on_road benar-benar kosong
    assert occ.snapshot_to_dict()["on_road_total"] == 0

    # Kendaraan turun melintasi pos di Gerbang A
    occ.register_exit("truck", gate="A", direction="menurun")
    occ.register_exit("mobil", gate="A", direction="menurun")

    snap = occ.snapshot_to_dict()
    # counts_out harus bertambah
    assert snap["counts_out"]["truck"] == 1
    assert snap["counts_out"]["mobil"] == 1
    # on_road tetap aman (tidak negatif)
    assert snap["on_road_total"] == 0


def test_q_volume_includes_both_in_and_out_directions():
    """Memastikan arus Q_total menggabungkan arus masuk (ekr naik) dan arus keluar (ekr turun)."""
    occ = RoadOccupancyManager()
    occ.reset()

    # 1 truk naik (ekr = 8.9)
    occ.register_entry("truck", gate="A", direction="menanjak")
    # 1 truk turun (ekr = 2.5)
    occ.register_exit("truck", gate="B", direction="menurun")

    # Total smp dalam event 15 menit = 8.9 + 2.5 = 11.4 smp
    # Proyeksi ke 1 jam = 11.4 * 4 = 45.6 smp/jam
    q = occ.calculate_volume_q_smp_jam()
    assert q >= 45.6


def test_kalman_filter_scale_stability():
    """Memastikan varians noise pengukuran R adaptif terhadap ukuran truk besar Full HD."""
    import numpy as np
    from src.detection.tracker import KalmanBoxFilter

    # Bounding box truk besar di Full HD (lebar 300px, tinggi 200px -> luas 60.000 px^2)
    bbox_large = [100, 100, 400, 300]
    kf = KalmanBoxFilter(bbox_large)

    r_mat = kf.R
    assert r_mat.shape == (4, 4)
    # Varians area untuk s=60.000 harus proporsional (bukan 25.0)
    assert r_mat[2, 2] > 1000.0

    # Periksa kestabilan inovasi dan invers matriks S
    s_cov = kf.innovation_covariance()
    s_inv = np.linalg.inv(s_cov)
    assert not np.isnan(s_inv).any()

    # Hitung Mahalanobis distance tidak boleh meledak
    d2 = kf.mahalanobis([105, 105, 405, 305])
    assert 0.0 <= d2 < 100.0


def test_dual_gate_soft_ttl_prevents_infinite_drift():
    """Memastikan kendaraan hantu yang tidak pernah keluar di Gate B dilepaskan setelah Soft TTL (2.5 jam)."""
    from datetime import datetime, timedelta
    from src.analytics.density import OnRoadVehicle

    occ = RoadOccupancyManager()
    occ.set_dual_gate_mode(True)
    occ.reset()

    # Masukkan kendaraan 3 jam yang lalu (melebihi Soft TTL 2.5 jam)
    old_time = datetime.now() - timedelta(hours=3)
    occ._on_road.append(OnRoadVehicle(class_name="truck", entered_at=old_time, gate="A"))

    # Masukkan kendaraan baru 10 menit yang lalu (masih valid dalam koridor)
    new_time = datetime.now() - timedelta(minutes=10)
    occ._on_road.append(OnRoadVehicle(class_name="mobil", entered_at=new_time, gate="A"))

    assert len(occ._on_road) == 2

    # Picu evaluasi expire transit
    occ._expire_transit()

    # Truk 3 jam yang lalu harus tereliminasi oleh Soft TTL, mobil 10 menit tetap ada
    assert len(occ._on_road) == 1
    assert occ._on_road[0].class_name == "mobil"


def test_gate_b_directional_registration():
    """Memastikan registrasi di Gerbang B: IN bernilai EKR menurun, OUT bernilai EKR menanjak."""
    occ = RoadOccupancyManager()
    occ.reset()

    # Gerbang B IN: kendaraan dari Solok menuju Padang (arah menurun)
    occ.register_entry("truck", gate="B", direction="menurun")
    last_event_in = occ._recent_events[-1]
    # EKR truk menurun adalah 2.50 (bukan 8.90)
    assert last_event_in.ekr_value == 2.50

    # Gerbang B OUT: kendaraan tiba di Solok setelah menanjak dari Padang (arah menanjak)
    occ.register_exit("truck", gate="B", direction="menanjak")
    last_event_out = occ._recent_events[-1]
    # EKR truk menanjak adalah 8.90
    assert last_event_out.ekr_value == 8.90


def test_adaptive_transit_delay_on_congestion():
    """Memastikan waktu transit adaptif memanjang dan kecepatan rata-rata turun saat beban jalan tinggi."""
    occ = RoadOccupancyManager()
    occ.reset()

    # 1. Saat jalan kosong, waktu transit harus di baseline (~1500 detik)
    base_sec = occ.get_adaptive_transit_sec()
    assert base_sec == 1500
    assert 38.0 <= occ.get_estimated_speed_kmh() <= 41.0

    # 2. Simulasikan lonjakan arus kendaraan (antrean truk berat di tanjakan)
    for _ in range(80):
        occ.register_entry("truck", gate="A", direction="menanjak")

    # Waktu transit adaptif harus memanjang secara proporsional sesuai fungsi BPR
    congested_sec = occ.get_adaptive_transit_sec()
    assert congested_sec > base_sec
    assert congested_sec >= 3000

    # Kecepatan estimasi harus turun dari 40 km/jam menjadi merayap (< 20 km/jam)
    congested_speed = occ.get_estimated_speed_kmh()
    assert congested_speed < 20.0

    # Snapshot harus memuat informasi baru
    snap = occ.snapshot_to_dict()
    assert "adaptive_transit_sec" in snap
    assert snap["adaptive_transit_sec"] == congested_sec
    assert "estimated_speed_kmh" in snap


def test_adaptive_transit_retention_single_gate():
    """Memastikan kendaraan dalam antrean macet tidak premature expire di Single Gate mode."""
    from datetime import datetime, timedelta
    from src.analytics.density import OnRoadVehicle

    occ = RoadOccupancyManager()
    occ.reset()
    occ.set_dual_gate_mode(False)  # Single gate mode

    # Masukkan 60 truk untuk memicu kondisi padat/macet
    for _ in range(60):
        occ.register_entry("truck", gate="A", direction="menanjak")

    # Ambil waktu transit adaptif yang telah memanjang
    adaptive_sec = occ.get_adaptive_transit_sec()
    assert adaptive_sec >= 3000  # Lebih dari 50 menit

    # Tambahkan kendaraan yang masuk 35 menit yang lalu (2100 detik yang lalu)
    # Jika menggunakan transit statis (1500 detik), kendaraan ini akan salah dihapus!
    entered_35m_ago = datetime.now() - timedelta(seconds=2100)
    occ._on_road.append(OnRoadVehicle(class_name="truck", entered_at=entered_35m_ago, gate="A"))

    initial_count = len(occ._on_road)
    occ._expire_transit()

    # Kendaraan 35 menit yang lalu HARUS TETAP ADA karena adaptive transit > 50 menit!
    assert len(occ._on_road) == initial_count



