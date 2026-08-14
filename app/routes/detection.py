from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import List
from app.database.connection import get_db
from app.schemas.detection import DetectionEventCreate, DetectionEventResponse
from app.services import detection_service

router = APIRouter(prefix="/api/detections", tags=["detections"])

@router.get("", response_model=List[DetectionEventResponse], summary="Get all detection events")
def get_detections(limit: int = Query(100, le=500), db: Session = Depends(get_db)):
    """
    Return the most recent detection events across all machines, newest first.
    """
    return detection_service.get_all_detection_events(db, limit=limit)

@router.get("/{mc_id}", response_model=List[DetectionEventResponse], summary="Get detection history for one machine")
def get_detections_for_machine(mc_id: str, limit: int = Query(100, le=500), db: Session = Depends(get_db)):
    """
    Return the full detection history for a specific machine, newest first.
    """
    return detection_service.get_detection_events_for_machine(db, mc_id, limit=limit)

@router.post("", response_model=DetectionEventResponse, status_code=201, summary="Log a new detection event")
def create_detection(event: DetectionEventCreate, db: Session = Depends(get_db)):
    """
    Log a new detection event (called automatically by the ML pipeline
    every time a new evidence clip is generated).
    """
    return detection_service.create_detection_event(db, event)