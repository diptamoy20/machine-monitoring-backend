import os
import json

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MODEL_PATH = os.path.join(PROJECT_ROOT, "best (5).pt")
ROI_CONFIG_PATH = os.path.join(PROJECT_ROOT, "roi_config.json")
DETECTION_DIR = os.path.join(PROJECT_ROOT, "Detection_temp")
FINAL_VIDEO_DIR = os.path.join(PROJECT_ROOT, "app", "static", "videos")
FINAL_IMAGE_DIR = os.path.join(PROJECT_ROOT, "app", "static", "images")
UTILIZATION_STATE_PATH = os.path.join(PROJECT_ROOT, "utilization_state.json")
UTILIZATION_LOG_PATH = os.path.join(PROJECT_ROOT, "utilization_log.txt")

API_BASE_URL = "http://localhost:8000"
MACHINE_IDS = [f"MC-{i:03d}" for i in range(1, 7)]

# Classification & Tracking Parameters
SMOOTHING_WINDOW = 5
LETTERBOX_SIZE = 224
CONFIDENCE_FLOOR = 35.0
RECORD_SECONDS = 30
DEBUG_TRIGGER = False

# MC-001 Motion Differencing Parameters
MC001_MOTION_PIXEL_THRESHOLD = 80
MC001_DIFF_THRESHOLD = 25

# MC-002 .. MC-006 YOLO Detection & Displacement Parameters (aligned with detection.py)
YOLO_CONF_THRESHOLD = 0.35
YOLO_IOU_THRESHOLD = 0.35
PIXELS_PER_METER = 50.0
MIN_DISPLACEMENT_METERS = 1.0
DISPLACEMENT_WINDOW_FRAMES = 15
MOVEMENT_WINDOW_1M_FRAMES = 300

# Active RTSP Streams (Channels 22 and 25 stopped; only 23 and 24 active)
RTSP_URLS = [
    "rtsp://admin:admin%40123@103.57.247.234:554/cam/realmonitor?channel=23&subtype=1",
    "rtsp://admin:admin%40123@103.57.247.234:554/cam/realmonitor?channel=24&subtype=1",
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
