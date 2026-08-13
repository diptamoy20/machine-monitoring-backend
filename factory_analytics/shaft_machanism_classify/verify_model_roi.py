import cv2
import json
import os
import numpy as np
from collections import deque, Counter
from ultralytics import YOLO

# ---------------- CONFIG ----------------
MODEL_PATH = r"D:\projct_demo\factory_analytics\runs\classify\factory_runs\roller_classifier\weights\best.pt"

VIDEO_PATHS = [
    r"D:\projct_demo\Trash\WhatsApp Video 2026-08-11 at 8.19.39 PM.mp4",
    r"D:\projct_demo\Trash\WhatsApp Video 2026-08-12 at 2.28.35 AM.mp4",
    # add more video paths here
]

ROI_CONFIG_PATH = "roi_config.json"
SMOOTHING_WINDOW = 10
LETTERBOX_SIZE = 224

model = YOLO(MODEL_PATH)


# ---------------- LETTERBOX (Fix 1) ----------------
def letterbox_crop(img, size=LETTERBOX_SIZE):
    h, w = img.shape[:2]
    scale = size / max(h, w)
    new_w, new_h = max(1, int(w * scale)), max(1, int(h * scale))
    resized = cv2.resize(img, (new_w, new_h))

    canvas = np.zeros((size, size, 3), dtype=np.uint8)
    top = (size - new_h) // 2
    left = (size - new_w) // 2
    canvas[top:top+new_h, left:left+new_w] = resized
    return canvas


# ---------------- SMOOTHING (Fix 2) ----------------
roi_history = {}

def get_smoothed_label(video_key, roi_idx, class_name):
    key = (video_key, roi_idx)
    if key not in roi_history:
        roi_history[key] = deque(maxlen=SMOOTHING_WINDOW)
    roi_history[key].append(class_name)
    most_common = Counter(roi_history[key]).most_common(1)[0][0]
    return most_common


# ---------------- ROI CONFIG ----------------
def load_all_roi_config():
    if os.path.exists(ROI_CONFIG_PATH):
        with open(ROI_CONFIG_PATH, "r") as f:
            return json.load(f)
    return {}

def save_all_roi_config(config):
    with open(ROI_CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)

def get_rois_for_video(video_path, first_frame, all_config):
    key = os.path.basename(video_path)

    if key in all_config:
        rois = all_config[key]
        print(f"[{key}] Loaded {len(rois)} saved ROI(s).")
        return rois

    print(f"[{key}] No saved ROI found.")
    print("Draw a box around each machine. Press ENTER after each box.")
    print("When done drawing all boxes, press ENTER/ESC on an empty selection.")
    boxes = cv2.selectROIs("Select Machine ROI(s)", first_frame, showCrosshair=True)
    cv2.destroyWindow("Select Machine ROI(s)")

    rois = [list(map(int, box)) for box in boxes if box[2] > 0 and box[3] > 0]

    if not rois:
        print(f"[{key}] No ROI selected — skipping this video.")
        return []

    all_config[key] = rois
    save_all_roi_config(all_config)
    print(f"[{key}] Saved {len(rois)} ROI(s) for future runs.")
    return rois


# ---------------- MAIN PROCESSING ----------------
def run_on_video(video_path, all_config):
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"Failed to open: {video_path}")
        return

    ret, first_frame = cap.read()
    if not ret:
        print(f"Could not read first frame of: {video_path}")
        return

    video_key = os.path.basename(video_path)
    rois = get_rois_for_video(video_path, first_frame, all_config)
    if not rois:
        cap.release()
        return

    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    window_name = f"Model Verification - {video_key}"
    print(f"Playing {video_path}. Press 'q' to move to next video.")

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break

        for idx, (x, y, w, h) in enumerate(rois):
            roi_crop = frame[y:y+h, x:x+w]
            if roi_crop.size == 0:
                continue

            model_input = letterbox_crop(roi_crop)
            results = model(model_input, verbose=False)

            for r in results:
                class_id = r.probs.top1
                raw_class_name = r.names[class_id]
                confidence = float(r.probs.top1conf) * 100

                class_name = get_smoothed_label(video_key, idx, raw_class_name)
                color = (0, 255, 0) if class_name == "running" else (0, 0, 255)

                cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)
                label = f"M{idx+1}: {class_name.upper()} ({confidence:.0f}%)"
                label_y = max(y - 10, 20)
                cv2.putText(frame, label, (x, label_y),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

        cv2.imshow(window_name, frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyWindow(window_name)


if __name__ == "__main__":
    all_config = load_all_roi_config()

    for video_path in VIDEO_PATHS:
        run_on_video(video_path, all_config)

    print("All videos processed.")