from sqlalchemy.orm import Session
from sqlalchemy import desc
from app.database.models import DetectionEvent
from app.schemas.detection import DetectionEventCreate
import logging

logger = logging.getLogger(__name__)


def create_detection_event(db: Session, event: DetectionEventCreate):
    from datetime import date
    from app.database.models import MachineUtilization

    # Snapshot today's undetected_time for this machine at the moment of the event
    today = date.today()
    util_row = (
        db.query(MachineUtilization)
        .filter(MachineUtilization.mc_id == event.mc_id, MachineUtilization.date == today)
        .first()
    )
    undetected_time = util_row.undetected_time if util_row else 0.0

    db_event = DetectionEvent(
        mc_id=event.mc_id,
        status=event.status,
        video_url=event.video_url,
        detected_at=event.detected_at,
        undetected_time=undetected_time,
    )
    db.add(db_event)
    db.commit()
    db.refresh(db_event)
    logger.info(f"Detection event logged: {db_event.mc_id} @ {db_event.detected_at} | undetected_time={undetected_time}")
    return db_event


def get_all_detection_events(db: Session, limit: int = 100):
    return (
        db.query(DetectionEvent)
        .order_by(desc(DetectionEvent.detected_at))
        .limit(limit)
        .all()
    )


def get_detection_events_for_machine(db: Session, mc_id: str, limit: int = 100):
    return (
        db.query(DetectionEvent)
        .filter(DetectionEvent.mc_id == mc_id)
        .order_by(desc(DetectionEvent.detected_at))
        .limit(limit)
        .all()
    )