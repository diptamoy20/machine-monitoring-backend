"""
Pydantic schemas for the inference API endpoints.
"""
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class InferenceRequest(BaseModel):
    """Request body for POST /api/inference/run"""
    mc_id: str = Field(..., description="Machine ID to run inference for (e.g. MC-001)")


class InferenceRunAllRequest(BaseModel):
    """Request body for POST /api/inference/run-all — runs inference for all mapped machines."""
    pass


class InferenceResult(BaseModel):
    """Response returned after a successful inference run."""
    mc_id: str = Field(..., description="Machine ID")
    status: str = Field(..., description="Normalized machine status: running / standby / stop")
    confidence: float = Field(..., description="Average prediction confidence (0-100)")
    frames_analyzed: int = Field(..., description="Number of frames analyzed")
    total_frames: int = Field(..., description="Total frames in the video")
    video_filename: str = Field(..., description="Source video filename used for inference")
    roi_index: int = Field(..., description="ROI index within the video")
    updated_at: datetime = Field(..., description="Timestamp when the DB was updated")


class InferenceBatchResult(BaseModel):
    """Response for run-all batch inference."""
    results: list[InferenceResult]
    errors: list[dict] = Field(default_factory=list, description="Machines that failed with error details")
    total_machines: int
    successful: int
    failed: int
