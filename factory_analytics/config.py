MODEL_PATH = r"D:\projct_demo\best.pt"

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

SMOOTHING_WINDOW = 10
LETTERBOX_SIZE = 224
CONFIDENCE_FLOOR = 90.0

RECORD_SECONDS = 30
DEBUG_TRIGGER = False
