import cv2
import json
import os
import numpy as np
from datetime import datetime
from collections import deque, Counter
from ultralytics import YOLO

# ---------------- CONFIG ----------------
MODEL_PATH = r"D:\projct_demo\factory_analytics\runs\classify\factory_runs\roller_classifier\weights\best.pt"

VIDEO_PATHS = [
    r"D:\projct_demo\Trash\WhatsApp Video 2026-08-11 at 8.19.39 PM.mp4",
    r"D:\projct_demo\Trash\WhatsApp Video 2026-08-12 at 2.28.35 AM.mp4",
]

ROI_CONFIG_PATH = "roi_config.json"
SMOOTHING_WINDOW = 10
LETTERBOX_SIZE = 224

DETECTION_DIR = "Detection_temp"
CONFIDENCE_THRESHOLD = 99.5       # FIXED: was 100.0, floats rarely hit exact 100
CONFIDENCE_FLOOR = 90.0           # below this, label as "uncertain"
RECORD_SECONDS = 30
DEBUG_TRIGGER = True              # prints raw confidence when label is "running", so you can verify

os.makedirs(DETECTION_DIR, exist_ok=True)
model = YOLO(MODEL_PATH)


# ---------------- LETTERBOX ----------------
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


# ---------------- SMOOTHING ----------------
roi_history = {}

def get_smoothed_label(video_key, roi_idx, class_name):
    key = (video_key, roi_idx)
    if key not in roi_history:
        roi_history[key] = deque(maxlen=SMOOTHING_WINDOW)
    roi_history[key].append(class_name)
    return Counter(roi_history[key]).most_common(1)[0][0]


# ---------------- CONFIDENCE FLOOR ----------------
def resolve_final_label(smoothed_label, confidence):
    if confidence < CONFIDENCE_FLOOR:
        return "uncertain"
    return smoothed_label


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


# ---------------- RECORDING ----------------
def generate_clip_filename():
    now = datetime.now()
    return os.path.join(DETECTION_DIR, now.strftime("%Y-%m-%d_%H-%M-%S") + ".mp4")

def start_recording(frame, fps):
    filename = generate_clip_filename()
    h, w = frame.shape[:2]
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(filename, fourcc, fps, (w, h))
    target_frames = int(round(fps * RECORD_SECONDS))
    print(f"[RECORDING STARTED] Saving to: {filename} ({target_frames} frames)")
    return writer, target_frames, filename


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

    recording = False
    video_writer = None
    frames_written = 0
    frames_target = 0
    clip_filename = None

    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps <= 0:
        fps = 25

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

                smoothed_label = get_smoothed_label(video_key, idx, raw_class_name)
                final_label = resolve_final_label(smoothed_label, confidence)

                if DEBUG_TRIGGER and final_label == "running":
                    print(f"[TRIGGER-CHECK] {video_key} M{idx+1} raw_confidence={confidence!r}")

                if final_label == "running":
                    color = (0, 255, 0)
                elif final_label == "stopped":
                    color = (0, 0, 255)
                else:
                    color = (0, 165, 255)

                cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)
                label = f"M{idx+1}: {final_label.upper()} ({confidence:.0f}%)"
                label_y = max(y - 10, 20)
                cv2.putText(frame, label, (x, label_y),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

                if confidence >= CONFIDENCE_THRESHOLD and final_label == "running" and not recording:
                    video_writer, frames_target, clip_filename = start_recording(frame, fps)
                    recording = True
                    frames_written = 0

        if recording:
            video_writer.write(frame)
            frames_written += 1
            if frames_written >= frames_target:
                video_writer.release()
                recording = False
                print(f"[RECORDING FINISHED] Saved: {clip_filename}")

        cv2.imshow(window_name, frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    if recording and video_writer is not None:
        video_writer.release()
        print(f"[RECORDING FINISHED - video ended early] Saved: {clip_filename}")

    cap.release()
    cv2.destroyWindow(window_name)


if __name__ == "__main__":
    all_config = load_all_roi_config()
    for video_path in VIDEO_PATHS:
        run_on_video(video_path, all_config)
    print("All videos processed.")