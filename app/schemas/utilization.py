from pydantic import BaseModel, ConfigDict
from typing import Dict, Optional
from datetime import datetime


class MachineUtilizationItem(BaseModel):
    runtime: float
    downtime: float
    idle: float
    total_available_time: float
    total_available_time_formatted: str
    utilization_percent: float
    undetected_time: float = 0.0


class UtilizationSyncRequest(BaseModel):
    data: Dict[str, MachineUtilizationItem]


class MachineUtilizationDBResponse(BaseModel):
    mc_id: str
    runtime: float
    downtime: float
    idle: float
    total_available_time: float
    total_available_time_formatted: str
    utilization_percent: float
    undetected_time: float = 0.0
    updated_at: datetime
    image_url: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class UtilizationHistoryItem(BaseModel):
    mc_id: str
    runtime_seconds: float
    downtime_seconds: float
    idle_seconds: float
    total_seconds: float
    utilization_percent: float
