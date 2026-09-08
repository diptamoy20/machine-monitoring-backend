import json
from datetime import datetime
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from app.database.connection import get_db
from app.database.models import MachineStatus
from app.schemas.machine import MachineResponse, MachineCreate, MachineUpdate
from app.services import machine_service

router = APIRouter(prefix="/api/machines", tags=["machines"])

UTILIZATION_STATE_PATH = Path(__file__).resolve().parent.parent.parent / "utilization_state.json"


@router.get("", response_model=List[MachineResponse], summary="Get all machines")
def get_machines(db: Session = Depends(get_db)):
    """
    Return the current status and metadata for all monitored machines.
    """
    return machine_service.get_all_machines(db)


from app.database.models import MachineUtilization

@router.get("/utilization/state", summary="Get day-wise utilization data from DB")
def get_utilization_state(
    from_date: Optional[datetime] = Query(None, alias="from", description="Start date (inclusive)"),
    to_date: Optional[datetime] = Query(None, alias="to", description="End date (inclusive)"),
    db: Session = Depends(get_db)
):
    """
    Returns one record per machine per calendar day within the given date range.
    The response is a list of day-wise utilization entries enriched with
    the machine's current image_url from MachineStatus.
    """
    # 1. Build image map from MachineStatus
    machine_statuses = db.query(MachineStatus).all()
    image_map = {ms.mc_id: ms.image_url for ms in machine_statuses}

    # 2. Query day-wise rows from MachineUtilization (no GROUP BY — raw daily records)
    query = db.query(MachineUtilization)

    if from_date:
        query = query.filter(MachineUtilization.date >= from_date.date())
    if to_date:
        query = query.filter(MachineUtilization.date <= to_date.date())

    rows = query.order_by(MachineUtilization.date, MachineUtilization.mc_id).all()

    # 3. Build response list — one entry per machine per day
    response_data = []
    for row in rows:
        response_data.append({
            "mc_id":                      row.mc_id,
            "date":                       str(row.date),
            "runtime":                    row.runtime,
            "downtime":                   row.downtime,
            "idle":                       row.idle,
            "total_available_time":       row.total_available_time,
            "total_available_time_formatted": row.total_available_time_formatted,
            "utilization_percent":        row.utilization_percent,
            "image_url":                  image_map.get(row.mc_id),
        })

    return response_data


@router.get("/{mc_id}", response_model=MachineResponse, summary="Get a single machine by ID")
def get_machine(mc_id: str, db: Session = Depends(get_db)):
    """
    Return the current status and metadata for a specific machine by its mc_id.
    """
    return machine_service.get_machine_by_mc_id(db, mc_id)


@router.post("", response_model=MachineResponse, status_code=201, summary="Create a new machine")
def create_machine(machine: MachineCreate, db: Session = Depends(get_db)):
    """
    Create a new machine with the specified details.
    """
    return machine_service.create_machine(db, machine)


@router.put("/{mc_id}", response_model=MachineResponse, summary="Update a machine")
def update_machine(mc_id: str, machine: MachineUpdate, db: Session = Depends(get_db)):
    """
    Update machine metadata and status.
    This can be used to process updates from an external system, like an AI prediction model.
    """
    return machine_service.update_machine(db, mc_id, machine)


@router.patch("/{mc_id}", response_model=MachineResponse, summary="Partially update a machine")
def patch_machine(mc_id: str, machine: MachineUpdate, db: Session = Depends(get_db)):
    """
    Partially update a machine's metadata or status.
    """
    return machine_service.update_machine(db, mc_id, machine)
