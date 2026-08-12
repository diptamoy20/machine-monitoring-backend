from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException
import logging
from app.database.models import MachineStatus
from app.schemas.machine import MachineCreate, MachineUpdate

logger = logging.getLogger(__name__)

def get_all_machines(db: Session):
    return db.query(MachineStatus).all()

def get_machine_by_mc_id(db: Session, mc_id: str):
    machine = db.query(MachineStatus).filter(MachineStatus.mc_id == mc_id).first()
    if not machine:
        raise HTTPException(status_code=404, detail="Machine not found")
    return machine

def create_machine(db: Session, machine: MachineCreate):
    db_machine = MachineStatus(
        mc_id=machine.mc_id,
        name=machine.name,
        image_url=machine.image_url,
        video_url=machine.video_url,
        status=machine.status
    )
    db.add(db_machine)
    try:
        db.commit()
        db.refresh(db_machine)
        logger.info(f"Machine created: {db_machine.mc_id}")
        return db_machine
    except IntegrityError:
        db.rollback()
        logger.error(f"Duplicate machine creation attempted for mc_id: {machine.mc_id}")
        raise HTTPException(status_code=409, detail="Machine ID already exists")

def update_machine(db: Session, mc_id: str, machine_update: MachineUpdate):
    db_machine = get_machine_by_mc_id(db, mc_id)
    
    update_data = machine_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_machine, key, value)
        
    db.commit()
    db.refresh(db_machine)
    logger.info(f"Machine updated: {mc_id}")
    return db_machine
