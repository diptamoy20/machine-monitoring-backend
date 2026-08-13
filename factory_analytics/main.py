"""
Entry point. Runs machine status verification across all configured videos:
- Loads/generates ROIs per video, each with a persistent unique machine_id
- Runs the classifier on each ROI per frame (letterbox + smoothing + confidence floor)
- Triggers a one-time 30s clip recording per machine on a confident
  running/stopped detection, auto-moves the clip to the static folder,
  and notifies the API so the machine's live status stays in sync
- Displays a live overlay window per video
"""

import cv2
from ultralytics import YOLO

import config
from roi_manager import ROIManager
from model_utils import letterbox_crop, LabelSmoother, resolve_final_label, get_label_color
from recorder import ClipRecorder


def run_on_video(video_path, model, roi_manager, smoother):
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"Failed to open: {video_path}")
        return

    ret, first_frame = cap.read()
    if not ret:
        print(f"Could not read first frame of: {video_path}")
        return

    video_key = video_path.split("\\")[-1].split("/")[-1]
    rois = roi_manager.get_rois(video_path, first_frame)
    if not rois:
        cap.release()
        return

    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    window_name = f"Model Verification - {video_key}"
    print(f"Playing {video_path}. Press 'q' to move to next video.")

    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps <= 0:
        fps = 25

    # One recorder per machine (keyed by machine_id), so each machine gets
    # its own independent one-time 30s clip + API update, not a shared one.
    recorders = {
        roi["machine_id"]: ClipRecorder(
            config.DETECTION_DIR,
            config.FINAL_VIDEO_DIR,
            config.RECORD_SECONDS,
            config.API_BASE_URL,
            roi["machine_id"],
        )
        for roi in rois
    }

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break

        for idx, roi in enumerate(rois):
            x, y, w, h = roi["bbox"]
            machine_id = roi["machine_id"]

            roi_crop = frame[y:y+h, x:x+w]
            if roi_crop.size == 0:
                continue

            model_input = letterbox_crop(roi_crop, config.LETTERBOX_SIZE)
            results = model(model_input, verbose=False)

            for r in results:
                class_id = r.probs.top1
                raw_class_name = r.names[class_id]
                confidence = float(r.probs.top1conf) * 100

                smoothed_label = smoother.smooth(video_key, idx, raw_class_name)
                final_label = resolve_final_label(smoothed_label, confidence, config.CONFIDENCE_FLOOR)

                if config.DEBUG_TRIGGER and final_label in ("running", "stopped"):
                    print(f"[TRIGGER-CHECK] {video_key} {machine_id} "
                          f"label={final_label} confidence={confidence!r}")

                color = get_label_color(final_label)
                cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)
                label = f"{machine_id}: {final_label.upper()} ({confidence:.0f}%)"
                label_y = max(y - 10, 20)
                cv2.putText(frame, label, (x, label_y),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

                should_trigger = final_label in ("running", "stopped")
                recorders[machine_id].maybe_start(frame, fps, should_trigger, final_label)

        # Write frames for any machine currently recording
        for recorder in recorders.values():
            recorder.write_if_recording(frame)

        cv2.imshow(window_name, frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    for recorder in recorders.values():
        recorder.stop(early=True)

    cap.release()
    cv2.destroyWindow(window_name)


def main():
    model = YOLO(config.MODEL_PATH)
    roi_manager = ROIManager(config.ROI_CONFIG_PATH, id_start=config.ROI_ID_START)
    smoother = LabelSmoother(config.SMOOTHING_WINDOW)

    for video_path in config.VIDEO_PATHS:
        run_on_video(video_path, model, roi_manager, smoother)

    print("All videos processed.")


if __name__ == "__main__":
    main()