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
    
    # Store aware datetime internally using UTC
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc), onupdate=lambda: datetime.datetime.now(datetime.timezone.utc))
