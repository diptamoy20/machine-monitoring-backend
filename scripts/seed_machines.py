import os
import sys
import logging
from sqlalchemy.orm import Session

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database.connection import SessionLocal
from app.database.models import MachineStatus

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Filenames that indicate "still placeholder data, safe to seed/reseed"
PLACEHOLDER_VIDEOS = {"/static/videos/video-machine-A.mp4", "/static/videos/video-machine-B.mp4"}

INITIAL_MACHINES = [
    {"mc_id": "MC-001", "name": "Machine 01", "status": "running", "image_url": "/static/videos/video-machine-A.mp4", "video_url": "/static/videos/video-machine-A.mp4"},
    {"mc_id": "MC-002", "name": "Machine 02", "status": "standby", "image_url": "/static/videos/video-machine-A.mp4", "video_url": "/static/videos/video-machine-A.mp4"},
    {"mc_id": "MC-003", "name": "Machine 03", "status": "stop", "image_url": "/static/videos/video-machine-B.mp4", "video_url": "/static/videos/video-machine-B.mp4"},
    {"mc_id": "MC-004", "name": "Machine 04", "status": "running", "image_url": "/static/videos/video-machine-B.mp4", "video_url": "/static/videos/video-machine-B.mp4"},
    {"mc_id": "MC-005", "name": "Machine 05", "status": "standby", "image_url": "/static/videos/video-machine-A.mp4", "video_url": "/static/videos/video-machine-A.mp4"},
    {"mc_id": "MC-006", "name": "Machine 06", "status": "running", "image_url": "/static/videos/video-machine-B.mp4", "video_url": "/static/videos/video-machine-B.mp4"},
]

def seed_data():
    db: Session = SessionLocal()
    try:
        for m_data in INITIAL_MACHINES:
            existing_machine = db.query(MachineStatus).filter(MachineStatus.mc_id == m_data["mc_id"]).first()

            if existing_machine:
                # SAFETY GUARD: only touch machines that still have placeholder
                # video data. If real detection data exists (video_url is not
                # a known placeholder), skip it entirely - never overwrite
                # real pipeline results.
                if existing_machine.video_url not in PLACEHOLDER_VIDEOS:
                    logger.info(f"SKIPPED {m_data['mc_id']} - has real data (video_url={existing_machine.video_url}), not overwriting.")
                    continue

                existing_machine.name = m_data["name"]
                existing_machine.status = m_data["status"]
                existing_machine.image_url = m_data["image_url"]
                existing_machine.video_url = m_data["video_url"]
                logger.info(f"Re-seeded placeholder machine {m_data['mc_id']}")
            else:
                new_machine = MachineStatus(
                    mc_id=m_data["mc_id"],
                    name=m_data["name"],
                    status=m_data["status"],
                    image_url=m_data["image_url"],
                    video_url=m_data["video_url"]
                )
                db.add(new_machine)
                logger.info(f"Created new machine {m_data['mc_id']}")

        db.commit()
        logger.info("Seed script completed successfully.")
    except Exception as e:
        db.rollback()
        logger.error(f"Error during seeding: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    seed_data()
