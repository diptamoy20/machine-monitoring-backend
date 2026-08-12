"""
Inference API routes.

POST /api/inference/run
    Run YOLO inference for a single machine by mc_id.
    Updates the machine status in PostgreSQL.
    Returns InferenceResult.

POST /api/inference/run-all
    Run YOLO inference for all machines with a video mapping.
    Sequential processing. Returns InferenceBatchResult.

GET /api/inference/status
    Returns model load status and available class names.

The frontend NEVER calls YOLO directly.
The frontend continues to use GET /api/machines for display.
"""
import logging
from fastapi import APIRouter, Depends, BackgroundTasks
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.config import settings
from app.schemas.inference import InferenceRequest, InferenceResult, InferenceBatchResult
from app.services import yolo_service
from app.ml.yolo import predictor

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/inference", tags=["inference"])


@router.get("/status", summary="YOLO model status")
def get_inference_status():
    """
    Check whether the YOLO model is loaded and ready.
    Returns model class names if available.
    """
    return {
        "model_loaded": predictor.is_model_loaded(),
        "class_names": predictor.get_class_names(),
        "model_path": settings.YOLO_MODEL_PATH,
        "device": settings.YOLO_DEVICE,
    }


@router.post("/run", response_model=InferenceResult, summary="Run inference for one machine")
def run_inference(
    request: InferenceRequest,
    db: Session = Depends(get_db),
):
    """
    Run YOLO inference on the pre-configured static video for the given machine.

    1. Validates mc_id exists in DB.
    2. Locates the video mapped to mc_id.
    3. Runs YOLO classification frame-by-frame on the ROI.
    4. Updates machine status in PostgreSQL.
    5. Returns prediction details.

    The frontend continues to call GET /api/machines to read the updated status.
    """
    logger.info(f"POST /api/inference/run — mc_id={request.mc_id}")
    return yolo_service.run_inference_for_machine(
        db=db,
        mc_id=request.mc_id,
        video_dir=settings.YOLO_VIDEO_DIR,
        smoothing_window=settings.YOLO_SMOOTHING_WINDOW,
        confidence_threshold=settings.YOLO_CONFIDENCE_THRESHOLD,
        max_frames=settings.YOLO_MAX_FRAMES,
    )


@router.post("/run-all", response_model=InferenceBatchResult, summary="Run inference for all machines")
def run_inference_all(
    db: Session = Depends(get_db),
):
    """
    Run YOLO inference sequentially for all machines that have a video mapping.
    Updates each machine's status in PostgreSQL.

    Returns a batch result with per-machine outcomes and any errors.
    """
    logger.info("POST /api/inference/run-all — running for all mapped machines")
    return yolo_service.run_inference_for_all_machines(
        db=db,
        video_dir=settings.YOLO_VIDEO_DIR,
        smoothing_window=settings.YOLO_SMOOTHING_WINDOW,
        confidence_threshold=settings.YOLO_CONFIDENCE_THRESHOLD,
        max_frames=settings.YOLO_MAX_FRAMES,
    )
