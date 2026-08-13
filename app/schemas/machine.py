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