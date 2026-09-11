import logging
from sqlalchemy.orm import Session
from app.database.models import MachineUtilization, MachineStatus
from app.schemas.utilization import UtilizationSyncRequest

logger = logging.getLogger(__name__)


from datetime import datetime, timezone

def sync_utilization(db: Session, payload: UtilizationSyncRequest):
    """Upsert one row per machine - overwrite, never insert duplicates."""
    updated = []
    current_date = datetime.now(timezone.utc).date()
    for mc_id, item in payload.data.items():
        row = db.query(MachineUtilization).filter(
            MachineUtilization.mc_id == mc_id,
            MachineUtilization.date == current_date
        ).first()
        if row is None:
            row = MachineUtilization(mc_id=mc_id, date=current_date)
            db.add(row)

        row.runtime = item.runtime
        row.downtime = item.downtime
        row.idle = item.idle
        row.total_available_time = item.total_available_time
        row.total_available_time_formatted = item.total_available_time_formatted
        row.utilization_percent = item.utilization_percent
        row.undetected_time = item.undetected_time
        row.offline_time = getattr(item, "offline_time", 0.0)
        row.total_time = getattr(item, "total_time", 0.0)
        updated.append(row)

    db.commit()
    for row in updated:
        db.refresh(row)

    logger.info(f"Utilization synced for {len(updated)} machine(s): {list(payload.data.keys())}")
    return updated


def get_all_utilization(db: Session):
    results = (
        db.query(MachineUtilization, MachineStatus.image_url)
        .outerjoin(MachineStatus, MachineUtilization.mc_id == MachineStatus.mc_id)
        .all()
    )
    
    response = []
    for util, img_url in results:
        util.image_url = img_url
        response.append(util)
        
    return response


def get_utilization_history(db: Session, date_from, date_to, mc_id: str = None):
    from app.database.models import DetectionEvent

    if mc_id:
        machine_ids = [mc_id]
    else:
        machine_ids = [row[0] for row in db.query(DetectionEvent.mc_id).distinct().all()]

    results = []
    for machine in machine_ids:
        prior_event = (
            db.query(DetectionEvent)
            .filter(DetectionEvent.mc_id == machine, DetectionEvent.detected_at < date_from)
            .order_by(DetectionEvent.detected_at.desc())
            .first()
        )
        events_in_range = (
            db.query(DetectionEvent)
            .filter(
                DetectionEvent.mc_id == machine,
                DetectionEvent.detected_at >= date_from,
                DetectionEvent.detected_at <= date_to,
            )
            .order_by(DetectionEvent.detected_at.asc())
            .all()
        )

        timeline = []
        if prior_event:
            timeline.append((date_from, prior_event.status))
        for e in events_in_range:
            timeline.append((e.detected_at, e.status))

        total_seconds = (date_to - date_from).total_seconds()
        runtime = 0.0
        downtime = 0.0

        for i in range(len(timeline)):
            seg_start = timeline[i][0]
            seg_status = timeline[i][1]
            seg_end = timeline[i + 1][0] if i + 1 < len(timeline) else date_to
            duration = max(0.0, (seg_end - seg_start).total_seconds())

            if seg_status == "running":
                runtime += duration
            elif seg_status in ("stop", "stopped"):
                downtime += duration

        idle = max(0.0, total_seconds - runtime - downtime)
        utilization = (runtime / total_seconds * 100) if total_seconds > 0 else 0.0

        results.append({
            "mc_id": machine,
            "runtime_seconds": round(runtime, 2),
            "downtime_seconds": round(downtime, 2),
            "idle_seconds": round(idle, 2),
            "total_seconds": round(total_seconds, 2),
            "utilization_percent": round(utilization, 2),
        })

    return results
