"""
Live production pipeline for RTSP camera streams - multi-camera,
multi-process, with cross-camera observation resolution.

Uses RtspStreamReader (rtsp_reader.py) for adaptive flow control,
smart protocol self-healing, watchdog, and exponential backoff.

Resolver returns "running", "stopped", or "offline" per machine each
tick, using real measured wall-clock Δt, feeding directly into
UtilizationTracker's Runtime/Downtime/Offline calculation.
"""

import cv2
import json
import time
import signal
import numpy as np
import requests
import multiprocessing
from datetime import datetime
from ultralytics import YOLO

import config
from roi_manager import ROIManager
from model_utils import letterbox_crop, crop_polygon, LabelSmoother, resolve_final_label, get_label_color
from recorder import ClipRecorder
from utilization_tracker import UtilizationTracker
from select_roi_rtsp import channel_key_from_url, cam_ip_from_url
from rtsp_reader import RtspStreamReader

OBSERVATION_STALE_SECONDS = 3.0
RESOLVER_TICK_SECONDS = 1.0


def draw_roi_annotation(frame, roi, final_label, confidence):
    color = get_label_color(final_label)
    machine_id = roi["machine_id"]

    if roi.get("shape") == "polygon":
        pts = np.array(roi["points"], dtype=np.int32)
        cv2.polylines(frame, [pts], isClosed=True, color=color, thickness=2)
        label_x, label_y = pts[0][0], max(pts[0][1] - 10, 20)
    else:
        x, y, w, h = roi["bbox"]
        cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)
        label_x, label_y = x, max(y - 10, 20)

    label = f"{machine_id}: {final_label.upper()} ({confidence:.0f}%)"
    cv2.putText(frame, label, (label_x, label_y),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)


def log_camera_offline_event(channel_key, timestamp):
    """Append one line per OFFLINE TRANSITION to camera_offline_log.txt."""
    timestamp_str = timestamp.strftime("%Y-%m-%d_%H-%M-%S")
    line = f"{timestamp_str}_{channel_key}_offline"
    try:
        with open(config.CAMERA_OFFLINE_LOG_PATH, "a") as f:
            f.write(line + "\n")
        print(f"[CAMERA OFFLINE LOGGED] {line}")
    except Exception as e:
        print(f"[CAMERA OFFLINE LOG ERROR] {e}")


def set_camera_status(shared_camera_status, channel_key, cam_ip, status):
    """Update this camera's status in the shared dict with a timestamp.
    Logs a discrete event to camera_offline_log.txt only on the
    TRANSITION into offline (not on every repeated offline check)."""
    now = datetime.now().astimezone()
    now_iso = now.isoformat()
    entry = dict(shared_camera_status.get(channel_key, {}))
    previous_status = entry.get("status")

    entry["cam_ip"] = cam_ip
    entry["status"] = status
    entry["last_checked"] = now_iso
    if status == "online":
        entry["last_online"] = now_iso
    shared_camera_status[channel_key] = entry

    if status == "offline" and previous_status != "offline":
        log_camera_offline_event(channel_key, now)


def camera_pipeline(url, stop_event, shared_observations, shared_camera_status):
    def handle_sigterm(signum, frame):
        raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM, handle_sigterm)

    channel_key = channel_key_from_url(url)
    cam_ip = cam_ip_from_url(url)

    roi_manager = ROIManager(config.ROI_CONFIG_PATH, valid_machine_ids=config.MACHINE_IDS)
    rois = roi_manager.all_config.get(channel_key, [])
    if not rois:
        print(f"[{channel_key}] No ROI configured. Run select_roi_rtsp.py first. Exiting this process.")
        set_camera_status(shared_camera_status, channel_key, cam_ip, "no_roi_configured")
        return

    print(f"[{channel_key}] Loading model...")
    model = YOLO(config.MODEL_PATH)
    smoother = LabelSmoother(config.SMOOTHING_WINDOW)

    recorders = {
        roi["machine_id"]: ClipRecorder(
            config.DETECTION_DIR,
            config.FINAL_VIDEO_DIR,
            config.FINAL_IMAGE_DIR,
            config.RECORD_SECONDS,
            config.API_BASE_URL,
            roi["machine_id"],
            cam_ip=cam_ip,
            cam_channel=channel_key,
        )
        for roi in rois
    }

    def on_connect():
        print(f"[{channel_key}] Connected.")
        set_camera_status(shared_camera_status, channel_key, cam_ip, "online")

    def on_disconnect():
        print(f"[{channel_key}] Lost connection - reader is auto-recovering...")
        set_camera_status(shared_camera_status, channel_key, cam_ip, "offline")
        for recorder in recorders.values():
            recorder.force_stop_if_recording()

    print(f"[{channel_key}] Starting RtspStreamReader...")
    set_camera_status(shared_camera_status, channel_key, cam_ip, "connecting")
    reader = RtspStreamReader(
        url,
        frame_timeout=5.0,
        on_connect=on_connect,
        on_disconnect=on_disconnect,
    )
    reader.start()

    fps = 25
    print(f"[{channel_key}] Starting detection loop.")

    try:
        while not stop_event.is_set():
            raw_frame = reader.read()

            if raw_frame is None:
                time.sleep(0.05)
                continue

            for idx, roi in enumerate(rois):
                machine_id = roi["machine_id"]

                if roi.get("shape") == "polygon":
                    roi_crop = crop_polygon(raw_frame, roi["points"])
                else:
                    x, y, w, h = roi["bbox"]
                    roi_crop = raw_frame[y:y + h, x:x + w]

                if roi_crop.size == 0:
                    continue

                model_input = letterbox_crop(roi_crop, config.LETTERBOX_SIZE)
                results = model(model_input, verbose=False)

                for r in results:
                    class_id = r.probs.top1
                    raw_class_name = r.names[class_id]
                    confidence = float(r.probs.top1conf) * 100

                    smoothed_label = smoother.smooth(channel_key, idx, raw_class_name)
                    final_label = resolve_final_label(smoothed_label, confidence, config.CONFIDENCE_FLOOR)

                    annotated_frame = raw_frame.copy()
                    draw_roi_annotation(annotated_frame, roi, final_label, confidence)

                    shared_observations[(machine_id, channel_key)] = (final_label, confidence, time.time())

                    should_trigger = final_label in ("running", "stopped")
                    recorders[machine_id].maybe_start(annotated_frame, fps, should_trigger, final_label)
                    recorders[machine_id].write_if_recording(annotated_frame)

    except KeyboardInterrupt:
        print(f"[{channel_key}] Interrupted.")

    finally:
        print(f"[{channel_key}] Cleaning up...")
        set_camera_status(shared_camera_status, channel_key, cam_ip, "offline")
        reader.stop()
        for recorder in recorders.values():
            recorder.stop(early=True)
        print(f"[{channel_key}] Stopped cleanly.")


def resolve_machine_states(shared_observations, machine_ids):
    now = time.time()
    resolved = {}

    for machine_id in machine_ids:
        best_label = None
        best_confidence = -1
        has_fresh_signal = False

        for (obs_machine_id, channel_key), (label, confidence, timestamp) in list(shared_observations.items()):
            if obs_machine_id != machine_id:
                continue
            if now - timestamp > OBSERVATION_STALE_SECONDS:
                continue
            has_fresh_signal = True
            if confidence > best_confidence:
                best_confidence = confidence
                best_label = label

        if not has_fresh_signal:
            resolved[machine_id] = "offline"
        elif best_label == "uncertain" or best_label is None:
            resolved[machine_id] = "stopped"
        else:
            resolved[machine_id] = best_label

    return resolved


def write_camera_log(shared_camera_status):
    data = dict(shared_camera_status)
    with open(config.CAMERA_LOG_PATH, "w") as f:
        json.dump(data, f, indent=2)


def get_all_configured_machine_ids():
    with open(config.ROI_CONFIG_PATH, "r") as f:
        roi_config = json.load(f)
    machine_ids = set()
    for channel_rois in roi_config.values():
        for roi in channel_rois:
            machine_ids.add(roi["machine_id"])
    return sorted(machine_ids)


def get_machine_to_channels_map():
    with open(config.ROI_CONFIG_PATH, "r") as f:
        roi_config = json.load(f)
    mapping = {}
    for channel_key, rois in roi_config.items():
        for roi in rois:
            mapping.setdefault(roi["machine_id"], []).append(channel_key)
    return mapping


def update_camera_status_for_machines(shared_camera_status, machine_to_channels):
    for machine_id, channels in machine_to_channels.items():
        is_online = any(
            shared_camera_status.get(ch, {}).get("status") == "online"
            for ch in channels
        )
        new_status = "online" if is_online else "offline"
        try:
            requests.patch(
                f"{config.API_BASE_URL}/api/machines/{machine_id}",
                json={"camera_status": new_status},
                timeout=10,
            )
        except requests.exceptions.RequestException as e:
            print(f"[CAMERA STATUS UPDATE ERROR] {machine_id}: {e}")


def main():
    manager = multiprocessing.Manager()
    shared_observations = manager.dict()
    shared_camera_status = manager.dict()
    stop_event = multiprocessing.Event()

    def handle_sigterm(signum, frame):
        print("Received SIGTERM, shutting down gracefully...")
        raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM, handle_sigterm)

    machine_ids = get_all_configured_machine_ids()
    machine_to_channels = get_machine_to_channels_map()
    print(f"Tracking {len(machine_ids)} machine(s): {machine_ids}")

    processes = []
    for url in config.RTSP_URLS:
        p = multiprocessing.Process(target=camera_pipeline, args=(url, stop_event, shared_observations, shared_camera_status), daemon=True)
        p.start()
        processes.append(p)

    tracker = UtilizationTracker(config.UTILIZATION_STATE_PATH, config.UTILIZATION_LOG_PATH, api_base_url=config.API_BASE_URL, undetected_log_path=config.UNDETECTED_LOG_PATH)
    last_sync_time = time.time()
    last_camera_log_time = time.time()

    print(f"Live monitoring started for {len(config.RTSP_URLS)} camera(s) across {len(processes)} process(es). Press Ctrl+C to stop.")

    last_tick_time = time.time()

    try:
        while True:
            time.sleep(RESOLVER_TICK_SECONDS)

            now = time.time()
            dt = now - last_tick_time
            last_tick_time = now

            resolved = resolve_machine_states(shared_observations, machine_ids)
            for machine_id, final_label in resolved.items():
                tracker.add_frame(machine_id, final_label, dt)

            if time.time() - last_sync_time >= config.UTILIZATION_SYNC_INTERVAL_SECONDS:
                tracker.write_all_logs()
                last_sync_time = time.time()

            if time.time() - last_camera_log_time >= config.CAMERA_LOG_WRITE_INTERVAL_SECONDS:
                write_camera_log(shared_camera_status)
                update_camera_status_for_machines(shared_camera_status, machine_to_channels)
                last_camera_log_time = time.time()

    except KeyboardInterrupt:
        print("Stopping all cameras...")
        stop_event.set()
        for p in processes:
            p.join(timeout=15)
        tracker.write_all_logs()
        write_camera_log(shared_camera_status)
        print("All cameras stopped.")


if __name__ == "__main__":
    main()
