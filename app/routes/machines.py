from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from app.database.connection import get_db
from app.schemas.machine import (
    MachineResponse, 
    MachineCreate, 
    MachineUpdate,
    MachineUtilizationRequest,
    MachineUtilizationResponse
)
from app.services import machine_service

router = APIRouter(prefix="/api/machines", tags=["machines"])

@router.get("", response_model=List[MachineResponse], summary="Get all machines")
def get_machines(db: Session = Depends(get_db)):
    """
    Return the current status and metadata for all monitored machines.
    """
    return machine_service.get_all_machines(db)

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

@router.post("/utilization", response_model=MachineUtilizationResponse, summary="Calculate machine utilization")
def calculate_machine_utilization(data: MachineUtilizationRequest):
    """
    Calculate the total available time and utilization percentage based on Runtime, Idle Time, and Downtime.
    This data is typically provided by the AI model for each machine.
    """
    total_available_time = data.runtime + data.idle_time + data.downtime
    
    # Handle division by zero
    utilization = 0.0
    if total_available_time > 0:
        utilization = (data.runtime / total_available_time) * 100
        
    return MachineUtilizationResponse(
        mc_id=data.mc_id,
        machine_name=data.machine_name,
        runtime=data.runtime,
        idle_time=data.idle_time,
        downtime=data.downtime,
        total_available_time=total_available_time,
        utilization=round(utilization, 2)
    )
@router.patch("/{mc_id}", response_model=MachineResponse, summary="Partially update a machine")
def patch_machine(mc_id: str, machine: MachineUpdate, db: Session = Depends(get_db)):
    """
    Partially update a machine's metadata or status.
    """
    return machine_service.update_machine(db, mc_id, machine)

import json
from pathlib import Path

UTILIZATION_STATE_PATH = Path(__file__).resolve().parent.parent.parent / "utilization_state.json"

@router.get("/utilization/state", summary="Get raw utilization data from JSON file")
def get_utilization_state():
    if not UTILIZATION_STATE_PATH.exists():
        raise HTTPException(status_code=404, detail=f"utilization_state.json not found at {UTILIZATION_STATE_PATH}")
    with open(UTILIZATION_STATE_PATH, "r") as f:
        return json.load(f)
