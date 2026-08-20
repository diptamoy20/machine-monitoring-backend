from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List
from app.database.connection import get_db
from app.schemas.utilization import UtilizationSyncRequest, MachineUtilizationDBResponse
from app.services import utilization_service

router = APIRouter(prefix="/api/utilization", tags=["utilization"])


@router.post("/sync", response_model=List[MachineUtilizationDBResponse], summary="Sync utilization data into DB")
def sync_utilization(payload: UtilizationSyncRequest, db: Session = Depends(get_db)):
    """
    Called automatically by UtilizationTracker.write_all_logs() every time
    the detection pipeline finishes a video. Upserts current utilization
    totals per machine into PostgreSQL.
    """
    return utilization_service.sync_utilization(db, payload)


@router.get("", response_model=List[MachineUtilizationDBResponse], summary="Get current utilization for all machines")
def get_utilization(db: Session = Depends(get_db)):
    """Return the current utilization snapshot for all machines from the database."""
    return utilization_service.get_all_utilization(db)
