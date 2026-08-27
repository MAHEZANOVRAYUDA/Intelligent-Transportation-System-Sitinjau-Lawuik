"""Database models and persistence."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, Float, Integer, String, create_engine, func
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from src.config import get_settings


class Base(DeclarativeBase):
    pass


class VehicleCrossing(Base):
    __tablename__ = "vehicle_crossings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=datetime.now, index=True)
    gate_id = Column(String(10), index=True)
    direction = Column(String(10))
    class_name = Column(String(20))
    confidence = Column(Float)
    track_id = Column(Integer, nullable=True)


class TrafficSnapshotRecord(Base):
    __tablename__ = "traffic_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    motor_on_road = Column(Integer, default=0)
    mobil_on_road = Column(Integer, default=0)
    bus_on_road = Column(Integer, default=0)
    truck_on_road = Column(Integer, default=0)
    volume_used = Column(Float, default=0.0)
    utilization_percent = Column(Float, default=0.0)
    status = Column(String(20))


class HourlyAggregate(Base):
    __tablename__ = "hourly_aggregates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    hour_start = Column(DateTime, index=True)
    gate_id = Column(String(10))
    motor_count = Column(Integer, default=0)
    mobil_count = Column(Integer, default=0)
    bus_count = Column(Integer, default=0)
    truck_count = Column(Integer, default=0)
    total_count = Column(Integer, default=0)
    avg_utilization = Column(Float, default=0.0)
    dominant_status = Column(String(20))


_engine = None
_SessionLocal = None


def init_db() -> sessionmaker[Session]:
    global _engine, _SessionLocal
    _, env = get_settings()
    db_url = env.database_url
    _engine = create_engine(db_url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(_engine)
    _SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False)
    return _SessionLocal


def get_session() -> Session:
    if _SessionLocal is None:
        init_db()
    return _SessionLocal()


def save_crossing(
    gate_id: str,
    direction: str,
    class_name: str,
    confidence: float,
    track_id: int | None = None,
) -> None:
    session = get_session()
    try:
        record = VehicleCrossing(
            gate_id=gate_id,
            direction=direction,
            class_name=class_name,
            confidence=confidence,
            track_id=track_id,
            timestamp=datetime.now(),
        )
        session.add(record)
        session.commit()
    finally:
        session.close()


def save_snapshot(snapshot_data: dict) -> None:
    session = get_session()
    try:
        on_road = snapshot_data.get("on_road", {})
        record = TrafficSnapshotRecord(
            motor_on_road=on_road.get("motor", 0),
            mobil_on_road=on_road.get("mobil", 0),
            bus_on_road=on_road.get("bus", 0),
            truck_on_road=on_road.get("truck", 0),
            volume_used=snapshot_data.get("volume_used_meter_lajur", 0),
            utilization_percent=snapshot_data.get("utilization_percent", 0),
            status=snapshot_data.get("status", "lancar"),
        )
        session.add(record)
        session.commit()
    finally:
        session.close()


def get_recent_snapshots(limit: int = 60) -> list[dict]:
    session = get_session()
    try:
        rows = (
            session.query(TrafficSnapshotRecord)
            .order_by(TrafficSnapshotRecord.timestamp.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "timestamp": r.timestamp.isoformat(),
                "on_road": {
                    "motor": r.motor_on_road,
                    "mobil": r.mobil_on_road,
                    "bus": r.bus_on_road,
                    "truck": r.truck_on_road,
                },
                "volume_used_meter_lajur": r.volume_used,
                "utilization_percent": r.utilization_percent,
                "status": r.status,
            }
            for r in reversed(rows)
        ]
    finally:
        session.close()


def clear_all_records() -> dict[str, int]:
    """Hapus semua event crossing, snapshot, dan agregat jam-an."""
    session = get_session()
    try:
        n_cross = session.query(VehicleCrossing).delete()
        n_snap = session.query(TrafficSnapshotRecord).delete()
        n_hour = session.query(HourlyAggregate).delete()
        session.commit()
        return {
            "vehicle_crossings": int(n_cross or 0),
            "traffic_snapshots": int(n_snap or 0),
            "hourly_aggregates": int(n_hour or 0),
        }
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_today_crossings() -> dict:
    """Akumulasi event tersimpan hari ini (waktu lokal), per arah dan kelas."""
    empty = {"motor": 0, "mobil": 0, "bus": 0, "truck": 0}
    counts_in = dict(empty)
    counts_out = dict(empty)
    session = get_session()
    try:
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        rows = (
            session.query(
                VehicleCrossing.direction,
                VehicleCrossing.class_name,
                func.count(VehicleCrossing.id),
            )
            .filter(VehicleCrossing.timestamp >= today)
            .group_by(VehicleCrossing.direction, VehicleCrossing.class_name)
            .all()
        )
        for direction, class_name, n in rows:
            target = counts_in if direction == "in" else counts_out
            if class_name in target:
                target[class_name] = int(n)
        by_class = {k: counts_in[k] + counts_out[k] for k in empty}
        return {
            "in": counts_in,
            "out": counts_out,
            "by_class": by_class,
            "total_in": sum(counts_in.values()),
            "total_out": sum(counts_out.values()),
        }
    finally:
        session.close()
