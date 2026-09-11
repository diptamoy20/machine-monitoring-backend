import os
import json

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MODEL_PATH = os.path.join(PROJECT_ROOT, "best.pt")
# VIDEO_PATHS = [
#     os.path.join(PROJECT_ROOT, "WhatsApp Video 2026-08-11 at 8.19.39 PM.mp4"),
#     os.path.join(PROJECT_ROOT, "WhatsApp Video 2026-08-12 at 2.28.35 AM.mp4"),
#     os.path.join(PROJECT_ROOT, "WhatsApp Video 2026-08-11 at 8.19.39 aP (3).mp4"),
#     os.path.join(PROJECT_ROOT, "WhatsAppVideo3.mp4"),
#     os.path.join(PROJECT_ROOT, "WhatsAppVideo2.mp4"),
#     os.path.join(PROJECT_ROOT, "WhatsAppVideo1.mp4"),
# ]

ROI_CONFIG_PATH = os.path.join(PROJECT_ROOT, "roi_config.json")
DETECTION_DIR = os.path.join(PROJECT_ROOT, "Detection_temp")
FINAL_VIDEO_DIR = os.path.join(PROJECT_ROOT, "app", "static", "videos")
FINAL_IMAGE_DIR = os.path.join(PROJECT_ROOT, "app", "static", "images")
UTILIZATION_STATE_PATH = os.path.join(PROJECT_ROOT, "utilization_state.json")
UTILIZATION_LOG_PATH = os.path.join(PROJECT_ROOT, "utilization_log.txt")

API_BASE_URL = "http://localhost:8000"
MACHINE_IDS = [f"MC-{i:03d}" for i in range(1, 7)]

SMOOTHING_WINDOW = 10
LETTERBOX_SIZE = 224
CONFIDENCE_FLOOR = 70.0
RECORD_SECONDS = 30
DEBUG_TRIGGER = False


RTSP_URLS = [
    "rtsp://admin:admin@123@103.57.247.234:554/cam/realmonitor?channel=22&subtype=1",
    "rtsp://admin:admin@123@103.57.247.234:554/cam/realmonitor?channel=23&subtype=1",
    "rtsp://admin:admin@123@103.57.247.234:554/cam/realmonitor?channel=24&subtype=1",
    "rtsp://admin:admin@123@103.57.247.234:554/cam/realmonitor?channel=25&subtype=1",
]

UTILIZATION_SYNC_INTERVAL_SECONDS = 60
RTSP_RECONNECT_DELAY_SECONDS = 5
CAMERA_LOG_PATH = os.path.join(PROJECT_ROOT, "camera_log.json")
CAMERA_LOG_WRITE_INTERVAL_SECONDS = 10
CAMERA_OFFLINE_LOG_PATH = os.path.join(PROJECT_ROOT, "camera_offline_log.txt")
UNDETECTED_LOG_PATH = os.path.join(PROJECT_ROOT, "undetected_machine_status_log.txt")


def utilization_state_path_for_channel(channel_key):
    return os.path.join(os.path.dirname(UTILIZATION_STATE_PATH), f"utilization_state_{channel_key}.json")


def utilization_log_path_for_channel(channel_key):
    return os.path.join(os.path.dirname(UTILIZATION_LOG_PATH), f"utilization_log_{channel_key}.txt")


def create_files_if_not_exist():
    required_directories = [
        os.path.dirname(MODEL_PATH),
        DETECTION_DIR,
        FINAL_VIDEO_DIR,
        FINAL_IMAGE_DIR,
        os.path.dirname(UTILIZATION_STATE_PATH),
        os.path.dirname(UTILIZATION_LOG_PATH),
        os.path.dirname(ROI_CONFIG_PATH),
    ]

    for directory in required_directories:
        if directory and not os.path.exists(directory):
            os.makedirs(directory, exist_ok=True)
            print(f"Directory created: {directory}")

    if not os.path.exists(UTILIZATION_STATE_PATH):
        default_state = {
            "status": "active",
            "current_utilization_percentage": 0.0,
            "last_updated": None
        }
        with open(UTILIZATION_STATE_PATH, 'w', encoding='utf-8') as json_file:
            json.dump(default_state, json_file, indent=4)
        print(f"File created: {UTILIZATION_STATE_PATH}")

    if not os.path.exists(UTILIZATION_LOG_PATH):
        with open(UTILIZATION_LOG_PATH, 'w', encoding='utf-8') as log_file:
            log_file.write("--- Utilization Log Initialized ---\n")
        print(f"File created: {UTILIZATION_LOG_PATH}")

    if not os.path.exists(ROI_CONFIG_PATH):
        with open(ROI_CONFIG_PATH, 'w', encoding='utf-8') as json_file:
            json.dump({"rois": {}}, json_file, indent=4)
        print(f"File created: {ROI_CONFIG_PATH}")


if __name__ == "__main__":
    create_files_if_not_exist()
