"""
Live production pipeline for RTSP camera streams - multi-camera,
multi-process, with cross-camera observation resolution.

Since the same physical machine can be visible from multiple cameras,
each camera process only *observes* (does not directly track) machine
state. Observations are written to a shared, process-safe dictionary.
A single resolver loop in the main process combines observations per
machine every second - using the highest-confidence fresh reading -
before updating the one shared UtilizationTracker and syncing to the
API. This avoids double-counting and conflicting readings when
multiple cameras cover the same machine.

Each machine gets its OWN annotated copy of the frame (only its own
ROI outline + label drawn on it), so saved snapshots/clips are
individual evidence per machine. Evidence filenames also include the
source camera's IP and channel for traceability.

Each camera process also reports its own connection status (online /
offline / connecting) into a shared dict. The main process periodically
writes this out to camera_log.json, and also PATCHes each machine's
camera_status in the database based on whether any camera covering
that machine is currently online.

Cleanup (releasing the capture, finishing/moving any in-progress
recordings) runs inside a try/finally, so it always executes even if
the process is interrupted (e.g. Ctrl+C) mid-frame - preventing
orphaned files stuck in Detection_temp.

Pipeline per camera process:
    1. Open the RTSP stream
    2. Load the ROI (drawn once, ahead of time, via select_roi_rtsp.py)
    3. Load the YOLO model (own copy, own process, own CPU core)
    4. Continuously classify, annotate individually, and report observations

Runs forever until Ctrl+C.
"""

import cv2
import json
import time
import numpy as np
import requests
import multiprocessing
import signal
import sys
from datetime import datetime
from ultralytics import YOLO

import config
from roi_manager import ROIManager
from model_utils import letterbox_crop, crop_polygon, LabelSmoother, resolve_final_label, get_label_color
from recorder import ClipRecorder
from utilization_tracker import UtilizationTracker
from select_roi_rtsp import channel_key_from_url, cam_ip_from_url

OBSERVATION_STALE_SECONDS = 3.0
RESOLVER_TICK_SECONDS = 1.0


def draw_roi_annotation(frame, roi, final_label, confidence):
    """Draw ONLY this machine's ROI outline + label onto the given frame (modifies in place)."""
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


def set_camera_status(shared_camera_status, channel_key, cam_ip, status):
    """Update this camera's status in the shared dict with a timestamp."""
    now = datetime.now().astimezone().isoformat()
    entry = dict(shared_camera_status.get(channel_key, {}))
    entry["cam_ip"] = cam_ip
    entry["status"] = status
    entry["last_checked"] = now
    if status == "online":
        entry["last_online"] = now
    shared_camera_status[channel_key] = entry


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

    fps = 25
    cap = None

    print(f"[{channel_key}] Starting detection loop.")

    try:
        while not stop_event.is_set():
            if cap is None or not cap.isOpened():
                print(f"[{channel_key}] Connecting to stream...")
                set_camera_status(shared_camera_status, channel_key, cam_ip, "connecting")
                cap = cv2.VideoCapture(url)
                if not cap.isOpened():
                    print(f"[{channel_key}] Connection failed. Retrying in {config.RTSP_RECONNECT_DELAY_SECONDS}s...")
                    set_camera_status(shared_camera_status, channel_key, cam_ip, "offline")
                    time.sleep(config.RTSP_RECONNECT_DELAY_SECONDS)
                    continue
                print(f"[{channel_key}] Connected.")
                set_camera_status(shared_camera_status, channel_key, cam_ip, "online")

            ret, raw_frame = cap.read()
            if not ret:
                print(f"[{channel_key}] Lost connection. Reconnecting...")
                set_camera_status(shared_camera_status, channel_key, cam_ip, "offline")
                for recorder in recorders.values():
                    recorder.force_stop_if_recording()
                cap.release()
                cap = None
                time.sleep(config.RTSP_RECONNECT_DELAY_SECONDS)
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
        if cap:
            cap.release()
        for recorder in recorders.values():
            recorder.stop(early=True)
        print(f"[{channel_key}] Stopped cleanly.")


def resolve_machine_states(shared_observations, machine_ids):
    now = time.time()
    resolved = {}

    for machine_id in machine_ids:
        best_label = None
        best_confidence = -1

        for (obs_machine_id, channel_key), (label, confidence, timestamp) in list(shared_observations.items()):
            if obs_machine_id != machine_id:
                continue
            if now - timestamp > OBSERVATION_STALE_SECONDS:
                continue
            if confidence > best_confidence:
                best_confidence = confidence
                best_label = label

        resolved[machine_id] = best_label if best_label is not None else "uncertain"

    return resolved


def write_camera_log(shared_camera_status):
    """Write the current camera status dict out to camera_log.json."""
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
    """Returns {machine_id: [channel_key, ...]} so we know which cameras cover each machine."""
    with open(config.ROI_CONFIG_PATH, "r") as f:
        roi_config = json.load(f)
    mapping = {}
    for channel_key, rois in roi_config.items():
        for roi in rois:
            mapping.setdefault(roi["machine_id"], []).append(channel_key)
    return mapping


def update_camera_status_for_machines(shared_camera_status, machine_to_channels):
    """PATCH each machine's camera_status: online if any covering camera is online, else offline."""
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
    def handle_sigterm(signum, frame):
        print("Received SIGTERM, shutting down gracefully...")
        raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM, handle_sigterm)

    manager = multiprocessing.Manager()
    shared_observations = manager.dict()
    shared_camera_status = manager.dict()
    stop_event = multiprocessing.Event()

    machine_ids = get_all_configured_machine_ids()
    machine_to_channels = get_machine_to_channels_map()
    print(f"Tracking {len(machine_ids)} machine(s): {machine_ids}")

    processes = []
    for url in config.RTSP_URLS:
        p = multiprocessing.Process(target=camera_pipeline, args=(url, stop_event, shared_observations, shared_camera_status), daemon=True)
        p.start()
        processes.append(p)

    tracker = UtilizationTracker(config.UTILIZATION_STATE_PATH, config.UTILIZATION_LOG_PATH, api_base_url=config.API_BASE_URL)
    last_sync_time = time.time()
    last_camera_log_time = time.time()

    print(f"Live monitoring started for {len(config.RTSP_URLS)} camera(s) across {len(processes)} process(es). Press Ctrl+C to stop.")

    try:
        while True:
            time.sleep(RESOLVER_TICK_SECONDS)

            resolved = resolve_machine_states(shared_observations, machine_ids)
            for machine_id, final_label in resolved.items():
                tracker.add_frame(machine_id, final_label, RESOLVER_TICK_SECONDS)

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
        update_camera_status_for_machines(shared_camera_status, machine_to_channels)
        print("All cameras stopped.")


if __name__ == "__main__":
    main()
