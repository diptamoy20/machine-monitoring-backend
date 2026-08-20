import logging
from sqlalchemy.orm import Session
from app.database.models import MachineUtilization
from app.schemas.utilization import UtilizationSyncRequest

logger = logging.getLogger(__name__)


def sync_utilization(db: Session, payload: UtilizationSyncRequest):
    """Upsert one row per machine - overwrite, never insert duplicates."""
    updated = []
    for mc_id, item in payload.data.items():
        row = db.query(MachineUtilization).filter(MachineUtilization.mc_id == mc_id).first()
        if row is None:
            row = MachineUtilization(mc_id=mc_id)
            db.add(row)

        row.runtime = item.runtime
        row.downtime = item.downtime
        row.idle = item.idle
        row.total_available_time = item.total_available_time
        row.total_available_time_formatted = item.total_available_time_formatted
        row.utilization_percent = item.utilization_percent
        updated.append(row)

    db.commit()
    for row in updated:
        db.refresh(row)

    logger.info(f"Utilization synced for {len(updated)} machine(s): {list(payload.data.keys())}")
    return updated


def get_all_utilization(db: Session):
    return db.query(MachineUtilization).all()
