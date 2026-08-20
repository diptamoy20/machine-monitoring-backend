from sqlalchemy.orm import Session
from sqlalchemy import desc
from app.database.models import DetectionEvent
from app.schemas.detection import DetectionEventCreate
import logging

logger = logging.getLogger(__name__)


def create_detection_event(db: Session, event: DetectionEventCreate):
    db_event = DetectionEvent(
        mc_id=event.mc_id,
        status=event.status,
        video_url=event.video_url,
        detected_at=event.detected_at,
    )
    db.add(db_event)
    db.commit()
    db.refresh(db_event)
    logger.info(f"Detection event logged: {db_event.mc_id} @ {db_event.detected_at}")
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