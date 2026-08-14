import datetime
from sqlalchemy import Column, Integer, String, DateTime
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
    mc_id = Column(String, index=True, nullable=False)  # matches MachineStatus.mc_id, no hard FK for simplicity
    status = Column(String, nullable=False)
    video_url = Column(String, nullable=False)
    detected_at = Column(DateTime(timezone=True), nullable=False)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc))