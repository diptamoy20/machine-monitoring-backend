"""
YOLO inference engine.

Refactored from the original verify_model_roi.py script.

Key changes from original:
- No cv2.imshow() / cv2.VideoCapture display (headless server safe)
- No hardcoded Windows paths
- Accepts configurable video_path, roi_index, and smoothing_window
- Returns a structured InferenceRawResult dict instead of printing
- Model is consumed from the predictor singleton (not loaded here)
- Supports YOLO_MAX_FRAMES to sample frames for performance

Preserved from original:
- letterbox_crop() — 224x224 padded resize (unchanged)
- Rolling majority-vote smoothing (deque + Counter)
- ROI loading from roi_config.json
"""
import cv2
import json
import logging
import numpy as np
from collections import deque, Counter
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_ROI_CONFIG_PATH = Path(__file__).parent / "config" / "roi_config.json"

LETTERBOX_SIZE = 224


# ---------------------------------------------------------------------------
# Letterbox crop (unchanged from original)
# ---------------------------------------------------------------------------
def letterbox_crop(img: np.ndarray, size: int = LETTERBOX_SIZE) -> np.ndarray:
    """
    Resize an image with padding to a square of `size` x `size`.
    Preserves aspect ratio.
    """
    h, w = img.shape[:2]
    scale = size / max(h, w)
    new_w = max(1, int(w * scale))
    new_h = max(1, int(h * scale))
    resized = cv2.resize(img, (new_w, new_h))

    canvas = np.zeros((size, size, 3), dtype=np.uint8)
    top = (size - new_h) // 2
    left = (size - new_w) // 2
    canvas[top:top + new_h, left:left + new_w] = resized
    return canvas


# ---------------------------------------------------------------------------
# ROI config loader
# ---------------------------------------------------------------------------
def load_roi_config() -> dict:
    """Load ROI rectangles from roi_config.json."""
    if _ROI_CONFIG_PATH.exists():
        with open(_ROI_CONFIG_PATH, "r") as f:
            return json.load(f)
    logger.warning(f"ROI config not found at {_ROI_CONFIG_PATH}")
    return {}


def get_rois_for_video(video_filename: str) -> list:
    """
    Return the list of ROI rectangles [x, y, w, h] for a given video filename.
    Returns empty list if not found.
    """
    config = load_roi_config()
    rois = config.get(video_filename, [])
    if not rois:
        logger.warning(f"No ROI config found for video '{video_filename}'")
    return rois


# ---------------------------------------------------------------------------
# Core inference function
# ---------------------------------------------------------------------------
def run_inference(
    video_path: str,
    roi_index: int,
    model,
    smoothing_window: int = 10,
    confidence_threshold: float = 0.5,
    max_frames: Optional[int] = None,
) -> dict:
    """
    Run YOLO classification inference on a single ROI of a video.

    Args:
        video_path:          Absolute or relative path to the video file.
        roi_index:           Index of the ROI to use from roi_config.json.
        model:               Loaded YOLO model (from predictor.get_model()).
        smoothing_window:    Number of recent frames for majority-vote smoothing.
        confidence_threshold: Minimum confidence to accept a prediction.
        max_frames:          If set, sample only up to this many frames (for speed).

    Returns:
        {
            "raw_class": str,          # majority-voted raw class name from model
            "confidence": float,       # average confidence over sampled frames (0-100)
            "frames_analyzed": int,    # number of frames actually processed
            "total_frames": int,       # total frames in video
            "roi_index": int,
            "video_filename": str,
        }

    Raises:
        FileNotFoundError:  if video_path does not exist.
        ValueError:         if ROI index is out of range or ROI is empty.
        RuntimeError:       if video cannot be opened or read.
    """
    video_path = str(video_path)
    video_filename = Path(video_path).name
    logger.info(f"[{video_filename}] Inference started — ROI index={roi_index}")

    # --- Validate video file ---
    if not Path(video_path).exists():
        raise FileNotFoundError(f"Video file not found: {video_path}")

    # --- Load ROI config ---
    rois = get_rois_for_video(video_filename)
    if not rois:
        raise ValueError(
            f"No ROI configuration found for video '{video_filename}'. "
            f"Ensure roi_config.json is correctly configured."
        )
    if roi_index >= len(rois):
        raise ValueError(
            f"roi_index={roi_index} is out of range. "
            f"Video '{video_filename}' has {len(rois)} ROI(s) defined (0-based)."
        )

    x, y, w, h = rois[roi_index]

    # --- Open video ---
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Failed to open video: {video_path}")

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    logger.info(f"[{video_filename}] Total frames: {total_frames}, ROI: x={x},y={y},w={w},h={h}")

    # --- Determine frame sampling stride ---
    if max_frames and total_frames > max_frames:
        stride = total_frames // max_frames
    else:
        stride = 1

    # --- Frame loop ---
    history: deque = deque(maxlen=smoothing_window)
    confidence_sum = 0.0
    frames_processed = 0
    frame_idx = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        frame_idx += 1

        # Skip frames based on stride (fast sampling)
        if stride > 1 and (frame_idx % stride != 0):
            continue

        # Crop ROI
        roi_crop = frame[y:y + h, x:x + w]
        if roi_crop.size == 0:
            continue

        # Prepare model input
        model_input = letterbox_crop(roi_crop)

        # Run YOLO classify inference
        results = model(model_input, verbose=False)

        for r in results:
            class_id = r.probs.top1
            raw_class_name = r.names[class_id]
            confidence = float(r.probs.top1conf) * 100

            if confidence >= (confidence_threshold * 100):
                history.append(raw_class_name)
                confidence_sum += confidence
                frames_processed += 1

    cap.release()

    if not history:
        logger.warning(
            f"[{video_filename}] No confident frames found (threshold={confidence_threshold}). "
            f"Returning 'stop' as safe fallback."
        )
        return {
            "raw_class": "stop",
            "confidence": 0.0,
            "frames_analyzed": 0,
            "total_frames": total_frames,
            "roi_index": roi_index,
            "video_filename": video_filename,
        }

    # Majority vote from smoothing history
    majority_class = Counter(history).most_common(1)[0][0]
    avg_confidence = round(confidence_sum / frames_processed, 2)

    logger.info(
        f"[{video_filename}] ROI={roi_index} → "
        f"class='{majority_class}' confidence={avg_confidence:.1f}% "
        f"frames_analyzed={frames_processed}/{total_frames}"
    )

    return {
        "raw_class": majority_class,
        "confidence": avg_confidence,
        "frames_analyzed": frames_processed,
        "total_frames": total_frames,
        "roi_index": roi_index,
        "video_filename": video_filename,
    }
