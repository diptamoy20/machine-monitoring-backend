"""
YOLO status mapper.

Responsibilities:
1. Normalize YOLO raw class names → application status values
   (running / stop / standby)
2. Map machine ID (mc_id) → video filename + ROI index using
   app/ml/yolo/config/machine_mapping.json

Notes:
- "standby" is reserved for future model support; current model
  only produces "running" and "stop".
- Any unknown class name falls back to "stop" with a warning log.
- Machine mapping is loaded once at module import time.
"""
import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Class name → application status mapping
# Current model produces: "running", "stop"
# "standby" is preserved for future model expansion.
# ---------------------------------------------------------------------------
_CLASS_TO_STATUS: dict[str, str] = {
    "running": "running",
    "stop": "stop",
    "stopped": "stop",        # alias
    "standby": "standby",     # reserved — model may produce this in future
    "idle": "standby",        # alias
}

_FALLBACK_STATUS = "stop"


def normalize_class_to_status(raw_class_name: str) -> str:
    """
    Map a YOLO class name to one of: 'running', 'standby', 'stop'.

    Falls back to 'stop' for unknown class names so the machine is
    never left in an invalid state.

    Args:
        raw_class_name: The class label returned by the YOLO model.

    Returns:
        One of 'running', 'standby', 'stop'.
    """
    normalized = _CLASS_TO_STATUS.get(raw_class_name.lower().strip())
    if normalized is None:
        logger.warning(
            f"Unknown YOLO class '{raw_class_name}'. "
            f"Falling back to status='{_FALLBACK_STATUS}'."
        )
        return _FALLBACK_STATUS
    return normalized


# ---------------------------------------------------------------------------
# Machine ID → Video + ROI mapping
# ---------------------------------------------------------------------------
_MAPPING_FILE = Path(__file__).parent / "config" / "machine_mapping.json"
_machine_mapping: dict = {}


def _load_machine_mapping() -> dict:
    """Load machine_mapping.json from disk."""
    try:
        with open(_MAPPING_FILE, "r") as f:
            data = json.load(f)
        logger.info(f"Machine-video mapping loaded: {list(data.keys())}")
        return data
    except FileNotFoundError:
        logger.error(f"machine_mapping.json not found at {_MAPPING_FILE}")
        return {}
    except json.JSONDecodeError as e:
        logger.error(f"Invalid machine_mapping.json: {e}")
        return {}


# Load at module import time
_machine_mapping = _load_machine_mapping()


def get_video_mapping_for_machine(mc_id: str) -> Optional[dict]:
    """
    Return the video + ROI mapping for a given machine ID.

    Returns:
        {
            "video_filename": "video-machine-A.mp4",
            "roi_index": 0
        }
        or None if mc_id is not mapped.
    """
    mapping = _machine_mapping.get(mc_id)
    if mapping is None:
        logger.warning(f"No video mapping found for mc_id='{mc_id}'")
    return mapping


def get_all_machine_ids() -> list[str]:
    """Return all mc_ids that have a video mapping defined."""
    return list(_machine_mapping.keys())
