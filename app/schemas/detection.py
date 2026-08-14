from pydantic import BaseModel, ConfigDict, Field
from typing import Literal
from datetime import datetime

DetectionStatusEnum = Literal["running", "standby", "stop"]

class DetectionEventCreate(BaseModel):
    mc_id: str = Field(..., description="The machine ID this detection belongs to")
    status: DetectionStatusEnum = Field(..., description="Detected status at time of recording")
    video_url: str = Field(..., description="URL of the saved evidence clip")
    detected_at: datetime = Field(..., description="Exact timestamp the clip was generated")

class DetectionEventResponse(BaseModel):
    id: int
    mc_id: str
    status: DetectionStatusEnum
    video_url: str
    detected_at: datetime
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)