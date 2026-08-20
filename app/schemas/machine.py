from pydantic import BaseModel, ConfigDict, Field
from typing import Literal, Optional
from datetime import datetime

StatusEnum = Literal["running", "standby", "stop"]

class MachineBase(BaseModel):
    name: str = Field(..., description="The name of the machine")
    image_url: Optional[str] = Field(None, description="The URL of the machine image")
    video_url: Optional[str] = Field(None, description="The URL of the machine video")
    status: StatusEnum = Field(..., description="The running status of the machine (running, standby, stop)")
    detected_at: Optional[datetime] = Field(None, description="Exact timestamp the current evidence video was generated")

class MachineCreate(MachineBase):
    mc_id: str = Field(..., description="The unique machine ID (e.g., MC-001)")

class MachineUpdate(BaseModel):
    name: Optional[str] = Field(None, description="The name of the machine")
    image_url: Optional[str] = Field(None, description="The URL of the machine image")
    video_url: Optional[str] = Field(None, description="The URL of the machine video")
    status: Optional[StatusEnum] = Field(None, description="The running status of the machine (running, standby, stop)")
    detected_at: Optional[datetime] = Field(None, description="Exact timestamp the current evidence video was generated")

class MachineResponse(MachineBase):
    id: int
    mc_id: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

class MachineUtilizationRequest(BaseModel):
    mc_id: str = Field(..., description="The unique machine ID (e.g., MC-001)")
    machine_name: str = Field(..., description="The name of the machine")
    runtime: float = Field(..., description="Runtime of the machine in hours")
    idle_time: float = Field(..., description="Idle time of the machine in hours")
    downtime: float = Field(..., description="Downtime of the machine in hours")

class MachineUtilizationResponse(BaseModel):
    mc_id: str = Field(..., description="The unique machine ID")
    machine_name: str = Field(..., description="The name of the machine")
    runtime: float = Field(..., description="Runtime in hours")
    idle_time: float = Field(..., description="Idle time in hours")
    downtime: float = Field(..., description="Downtime in hours")
    total_available_time: float = Field(..., description="Total available time in hours (Runtime + Idle Time + Downtime)")
    utilization: float = Field(..., description="Utilization percentage (Runtime / Total Available Time * 100)")