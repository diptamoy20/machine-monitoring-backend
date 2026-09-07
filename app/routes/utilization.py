from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from typing import List
from datetime import datetime, timedelta
from app.database.connection import get_db
from app.schemas.utilization import UtilizationSyncRequest, MachineUtilizationDBResponse, UtilizationHistoryItem
from app.services import utilization_service

router = APIRouter(prefix="/api/utilization", tags=["utilization"])

router = APIRouter(prefix="/api/utilization", tags=["utilization"])
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


@router.get("/history", response_model=List[UtilizationHistoryItem], summary="Get utilization for a date range, computed from detection history")
def get_utilization_history_endpoint(
    from_: str = Query(..., alias="from", description="Start date, YYYY-MM-DD"),
    to: str = Query(..., description="End date, YYYY-MM-DD (inclusive)"),
    mc_id: str = Query(None, description="Optional - filter to a single machine"),
    db: Session = Depends(get_db),
):
    try:
        date_from = datetime.strptime(from_, "%Y-%m-%d").astimezone()
        date_to = (datetime.strptime(to, "%Y-%m-%d") + timedelta(days=1)).astimezone()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")

    if date_from >= date_to:
        raise HTTPException(status_code=400, detail="from must be before to.")

    return utilization_service.get_utilization_history(db, date_from, date_to, mc_id)
