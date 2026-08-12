"""
YOLO Service — orchestration layer between the inference engine and the database.

Responsibilities:
- Validate that mc_id exists in the database
- Look up video + ROI mapping for mc_id
- Resolve the video file path
- Call the YOLO inference engine
- Normalize the raw YOLO class to application status
- Update machine_status table via machine_service
- Return a structured InferenceResult

The YOLO ML code (app/ml/yolo/) has NO knowledge of the database.
The database layer has NO knowledge of YOLO internals.
This service is the only bridge between them.
"""
import logging
from pathlib import Path
from sqlalchemy.orm import Session
from fastapi import HTTPException

from app.ml.yolo import predictor
from app.ml.yolo import inference as yolo_inference
from app.ml.yolo import mapper
from app.services import machine_service
from app.schemas.machine import MachineUpdate
from app.schemas.inference import InferenceResult, InferenceBatchResult

logger = logging.getLogger(__name__)


def run_inference_for_machine(
    db: Session,
    mc_id: str,
    video_dir: str,
    smoothing_window: int = 10,
    confidence_threshold: float = 0.5,
    max_frames: int = None,
) -> InferenceResult:
    """
    Run YOLO inference for a single machine and update PostgreSQL.

    Args:
        db:                   SQLAlchemy session.
        mc_id:                Machine ID (e.g. 'MC-001').
        video_dir:            Directory containing inference videos.
        smoothing_window:     Frames to consider for majority-vote smoothing.
        confidence_threshold: Minimum confidence to accept a prediction (0-1).
        max_frames:           If set, limits frames sampled for speed.

    Returns:
        InferenceResult schema.

    Raises:
        HTTPException 404: mc_id not found in database.
        HTTPException 400: No video mapping for mc_id, or video file missing.
        HTTPException 503: YOLO model not loaded.
        HTTPException 500: Inference engine failure.
    """
    logger.info(f"Inference requested for mc_id={mc_id}")

    # 1. Validate machine exists in DB
    machine = machine_service.get_machine_by_mc_id(db, mc_id)  # raises 404 if not found

    # 2. Check model is loaded
    if not predictor.is_model_loaded():
        raise HTTPException(
            status_code=503,
            detail="YOLO model is not available. Check server logs for model loading errors."
        )

    # 3. Resolve video + ROI mapping
    mapping = mapper.get_video_mapping_for_machine(mc_id)
    if not mapping:
        raise HTTPException(
            status_code=400,
            detail=f"No video mapping configured for mc_id='{mc_id}'. "
                   f"Update app/ml/yolo/config/machine_mapping.json."
        )

    video_filename = mapping["video_filename"]
    roi_index = mapping["roi_index"]
    video_path = Path(video_dir) / video_filename

    if not video_path.exists():
        raise HTTPException(
            status_code=400,
            detail=f"Video file not found: {video_path}. "
                   f"Ensure YOLO_VIDEO_DIR is correctly configured and videos are present."
        )

    # 4. Run inference
    try:
        model = predictor.get_model()
        raw_result = yolo_inference.run_inference(
            video_path=str(video_path),
            roi_index=roi_index,
            model=model,
            smoothing_window=smoothing_window,
            confidence_threshold=confidence_threshold,
            max_frames=max_frames,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Inference engine error for mc_id={mc_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Inference failed: {str(e)}")

    # 5. Normalize class → status
    status = mapper.normalize_class_to_status(raw_result["raw_class"])
    logger.info(f"mc_id={mc_id} | raw_class='{raw_result['raw_class']}' → status='{status}'")

    # 6. Update PostgreSQL
    update = MachineUpdate(status=status)
    updated_machine = machine_service.update_machine(db, mc_id, update)
    logger.info(f"mc_id={mc_id} status updated to '{status}' in database")

    return InferenceResult(
        mc_id=mc_id,
        status=status,
        confidence=raw_result["confidence"],
        frames_analyzed=raw_result["frames_analyzed"],
        total_frames=raw_result["total_frames"],
        video_filename=raw_result["video_filename"],
        roi_index=raw_result["roi_index"],
        updated_at=updated_machine.updated_at,
    )


def run_inference_for_all_machines(
    db: Session,
    video_dir: str,
    smoothing_window: int = 10,
    confidence_threshold: float = 0.5,
    max_frames: int = None,
) -> InferenceBatchResult:
    """
    Run YOLO inference for all machines that have a video mapping defined.

    Processes machines sequentially. Failures for individual machines
    are collected and returned without stopping the batch.

    Returns:
        InferenceBatchResult with per-machine results and error list.
    """
    all_mc_ids = mapper.get_all_machine_ids()
    results = []
    errors = []

    for mc_id in all_mc_ids:
        try:
            result = run_inference_for_machine(
                db=db,
                mc_id=mc_id,
                video_dir=video_dir,
                smoothing_window=smoothing_window,
                confidence_threshold=confidence_threshold,
                max_frames=max_frames,
            )
            results.append(result)
        except HTTPException as e:
            logger.warning(f"Inference failed for mc_id={mc_id}: {e.detail}")
            errors.append({"mc_id": mc_id, "error": e.detail, "status_code": e.status_code})
        except Exception as e:
            logger.error(f"Unexpected error for mc_id={mc_id}: {e}")
            errors.append({"mc_id": mc_id, "error": str(e), "status_code": 500})

    return InferenceBatchResult(
        results=results,
        errors=errors,
        total_machines=len(all_mc_ids),
        successful=len(results),
        failed=len(errors),
    )
