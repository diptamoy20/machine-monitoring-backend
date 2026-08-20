import os
import json

# ==========================================
# CONFIGURATION CONSTANTS
# ==========================================
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
UTILIZATION_STATE_PATH = r"D:\projct_demo\utilization_state.json"
UTILIZATION_LOG_PATH = r"D:\projct_demo\utilization_log.txt"

API_BASE_URL = "http://localhost:8000"
MACHINE_IDS = [f"MC-{i:03d}" for i in range(1, 7)]

SMOOTHING_WINDOW = 10
LETTERBOX_SIZE = 224
CONFIDENCE_FLOOR = 90.0
RECORD_SECONDS = 30
DEBUG_TRIGGER = False


# ==========================================
# INITIALIZATION LOGIC
# ==========================================
def create_files_if_not_exist():
    # 1. Collect all directories that must exist for this app to run
    required_directories = [
        os.path.dirname(MODEL_PATH),
        DETECTION_DIR,
        FINAL_VIDEO_DIR,
        FINAL_IMAGE_DIR,
        os.path.dirname(UTILIZATION_STATE_PATH),
        os.path.dirname(UTILIZATION_LOG_PATH),
        os.path.dirname(ROI_CONFIG_PATH)
    ]

    # Create all required folders safely (including nested app/static structures)
    for directory in required_directories:
        if directory and not os.path.exists(directory):
            os.makedirs(directory, exist_ok=True)
            print(f"Directory created: {directory}")

    # 2. Automatically create the JSON state file with default layout
    if not os.path.exists(UTILIZATION_STATE_PATH):
        default_state = {
            "status": "active",
            "current_utilization_percentage": 0.0,
            "last_updated": None
        }
        with open(UTILIZATION_STATE_PATH, 'w', encoding='utf-8') as json_file:
            json.dump(default_state, json_file, indent=4)
        print(f"File created: {UTILIZATION_STATE_PATH}")

    # 3. Automatically create the TXT log file with a header
    if not os.path.exists(UTILIZATION_LOG_PATH):
        with open(UTILIZATION_LOG_PATH, 'w', encoding='utf-8') as log_file:
            log_file.write("--- Utilization Log Initialized ---\n")
        print(f"File created: {UTILIZATION_LOG_PATH}")

    # 4. Initialize an empty ROI config if missing to prevent pipeline crashes
    if not os.path.exists(ROI_CONFIG_PATH):
        with open(ROI_CONFIG_PATH, 'w', encoding='utf-8') as json_file:
            json.dump({"rois": {}}, json_file, indent=4)
        print(f"File created: {ROI_CONFIG_PATH}")


if __name__ == "__main__":
    create_files_if_not_exist()