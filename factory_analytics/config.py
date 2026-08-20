<<<<<<< HEAD
import os
MODEL_PATH = r"D:\project\Machine Monitoring backend (Python)\machine-monitoring-backend\best.pt"

VIDEO_PATHS = [
    r"D:\project\Machine Monitoring backend (Python)\machine-monitoring-backend\WhatsApp Video 2026-08-12 at 2.28.35 AM.mp4",
    r"D:\project\Machine Monitoring backend (Python)\machine-monitoring-backend\WhatsApp Video 2026-08-11 at 8.19.39 PM.mp4",
]

ROI_CONFIG_PATH = r"D:\project\Machine Monitoring backend (Python)\machine-monitoring-backend\roi_config.json"
DETECTION_DIR = r"D:\project\Machine Monitoring backend (Python)\machine-monitoring-backend\Detection_temp"
os.makedirs(DETECTION_DIR, exist_ok=True)
FINAL_VIDEO_DIR = r"D:\project\Machine Monitoring backend (Python)\machine-monitoring-backend\app\static\videos"
API_BASE_URL = "http://localhost:8000"

# Set to the highest MC number already used in your database (MC-001..MC-006),
# so newly auto-generated IDs start at MC-007 and never collide.
ROI_ID_START = 6
=======
﻿MODEL_PATH = r"D:\projct_demo\best.pt"

VIDEO_PATHS = [
    r"D:\projct_demo\WhatsApp Video 2026-08-11 at 8.19.39 PM.mp4",
    r"D:\projct_demo\WhatsApp Video 2026-08-12 at 2.28.35 AM.mp4",
    r"D:\projct_demo\WhatsApp Video 2026-08-11 at 8.19.39 aP (3).mp4",
    r"D:\projct_demo\WhatsAppVideo3.mp4",
    r"D:\projct_demo\WhatsAppVideo2.mp4",
    r"D:\projct_demo\WhatsAppVideo1.mp4",
]

ROI_CONFIG_PATH = r"D:\projct_demo\roi_config.json"
DETECTION_DIR = r"D:\projct_demo\Detection_temp"
FINAL_VIDEO_DIR = r"D:\projct_demo\app\static\videos"
FINAL_IMAGE_DIR = r"D:\projct_demo\app\static\images"
API_BASE_URL = "http://localhost:8000"

MACHINE_IDS = [f"MC-{i:03d}" for i in range(1, 7)]

>>>>>>> 650eb7c7c690ae5ec5550a171a275e596753c933
SMOOTHING_WINDOW = 10
LETTERBOX_SIZE = 224
CONFIDENCE_FLOOR = 90.0

RECORD_SECONDS = 30
DEBUG_TRIGGER = False
