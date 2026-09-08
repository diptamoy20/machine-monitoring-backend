import datetime
from sqlalchemy import Column, Integer, String, DateTime, Float, Date
from app.database.connection import Base

class MachineStatus(Base):
    __tablename__ = "machine_status"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    mc_id = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=False)
    image_url = Column(String, nullable=True)
    video_url = Column(String, nullable=True)
    status = Column(String, nullable=False)
    detected_at = Column(DateTime(timezone=True), nullable=True)
    camera_status = Column(String, nullable=False, default="offline")
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc), onupdate=lambda: datetime.datetime.now(datetime.timezone.utc))


class DetectionEvent(Base):
    """
    One row per detection/recording event. Unlike MachineStatus.video_url
    (which only ever holds the LATEST clip), this table preserves every
    clip ever generated, so a full history can be queried per machine.
    """
    __tablename__ = "detection_events"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    mc_id = Column(String, index=True, nullable=False)
    status = Column(String, nullable=False)
    video_url = Column(String, nullable=False)
    detected_at = Column(DateTime(timezone=True), nullable=False)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc))


class MachineUtilization(Base):
    """
    One row per machine per calendar day. Accumulated from the detection
    pipeline via /api/utilization/sync. Each day's bucket builds up live
    throughout that day. Previous days are frozen and preserved.
    """
    __tablename__ = "machine_utilization"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    mc_id = Column(String, index=True, nullable=False)
    date = Column(Date, default=lambda: datetime.datetime.now(datetime.timezone.utc).date(), nullable=False)
    runtime = Column(Float, nullable=False, default=0.0)
    downtime = Column(Float, nullable=False, default=0.0)
    idle = Column(Float, nullable=False, default=0.0)
    total_available_time = Column(Float, nullable=False, default=0.0)
    total_available_time_formatted = Column(String, nullable=True)
    utilization_percent = Column(Float, nullable=False, default=0.0)

    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc), onupdate=lambda: datetime.datetime.now(datetime.timezone.utc))

