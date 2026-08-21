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


class UtilizationSyncRequest(BaseModel):
    """Body shape sent by UtilizationTracker._notify_api() - mirrors utilization_state.json exactly."""
    data: Dict[str, MachineUtilizationItem]


class MachineUtilizationDBResponse(BaseModel):
    mc_id: str
    runtime: float
    downtime: float
    idle: float
    total_available_time: float
    total_available_time_formatted: str
    utilization_percent: float
    updated_at: datetime
    image_url: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)
