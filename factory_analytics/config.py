"""
Central configuration for the factory machine monitoring system.
Edit this file to change models, videos, thresholds, or paths.
"""

MODEL_PATH = r"D:\projct_demo\factory_analytics\runs\classify\factory_runs\roller_classifier\weights\best.pt"

# Add or remove video paths here - each gets its own ROI set, saved separately
VIDEO_PATHS = [
    r"D:\projct_demo\Trash\WhatsApp Video 2026-08-11 at 8.19.39 PM.mp4",
    r"D:\projct_demo\Trash\WhatsApp Video 2026-08-12 at 2.28.35 AM.mp4",
    r"D:\projct_demo\Trash\WhatsApp Video 2026-08-11 at 8.19.39 aP (3).mp4",
    r"D:\projct_demo\Trash\WhatsApp Video 2026-08-11 at 8.19.39 aP (2).mp4",
    # r"D:\projct_demo\Trash\your_new_video.mp4",   # <- add new videos here
]

ROI_CONFIG_PATH = "roi_config.json"
DETECTION_DIR = "Detection_temp"

# Model / classification tuning
SMOOTHING_WINDOW = 10
LETTERBOX_SIZE = 224
CONFIDENCE_FLOOR = 90.0        # below this, label shown as "uncertain" (also gates recording)

# Recording tuning
RECORD_SECONDS = 30
# NOTE: CONFIDENCE_THRESHOLD (requiring ~100%) has been removed.
# Recording now triggers on ANY confident "running" or "stopped" result
# (i.e. anything NOT flagged "uncertain" per CONFIDENCE_FLOOR above).
# Only ONE clip is saved per video processing session - see recorder.py.

DEBUG_TRIGGER = False