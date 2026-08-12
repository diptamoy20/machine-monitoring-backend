"""
YOLO model singleton loader.

Loads the YOLO classification model once at application startup
and exposes it via get_model() for reuse across all inference requests.

Thread-safety: ultralytics YOLO inference is GIL-bound; for CPU-only
sequential POC requests this is sufficient. GPU concurrent access
should use a request queue when that path is enabled.
"""
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_model = None  # module-level singleton


def load_model(model_path: str, device: str = "cpu") -> None:
    """
    Load the YOLO model into memory.
    Called once at FastAPI startup.

    Args:
        model_path: Path to the .pt weights file.
        device: 'cpu' or '0' (CUDA GPU index).
    """
    global _model
    try:
        from ultralytics import YOLO  # imported here so FastAPI starts even if ultralytics is absent

        path = Path(model_path)
        if not path.exists():
            raise FileNotFoundError(f"Model weights not found at: {model_path}")

        logger.info(f"Loading YOLO model from {model_path} on device={device}")
        _model = YOLO(str(path))
        # Warm-up: move model to correct device
        _model.to(device)
        logger.info(f"YOLO model loaded successfully. Classes: {_model.names}")
    except Exception as e:
        logger.error(f"Failed to load YOLO model: {e}")
        _model = None
        raise


def get_model():
    """
    Return the loaded YOLO model singleton.
    Raises RuntimeError if the model was not loaded successfully.
    """
    if _model is None:
        raise RuntimeError(
            "YOLO model is not loaded. "
            "Ensure load_model() was called at application startup."
        )
    return _model


def is_model_loaded() -> bool:
    """Return True if the model singleton is available."""
    return _model is not None


def get_class_names() -> Optional[dict]:
    """Return the class names dict from the loaded model, or None."""
    if _model is None:
        return None
    return _model.names
