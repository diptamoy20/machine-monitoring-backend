"""
Live production pipeline for RTSP camera streams - multi-camera, multi-process.
Combines:
1. MC-001: Polygon-masked frame differencing motion evaluation (mc-001_motion_status.py).
2. MC-002..MC-006: YOLO object detection + centroid spatial displacement tracking in meters (detection.py).
3. Cross-camera observation resolution & continuous 24h utilization tracking.
4. Auto-triggered snapshot & 30s transcoded video clip recording with REST API integration.
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
from model_utils import (
    crop_polygon,
    polygon_centroid,
    get_label_color,
    LabelSmoother,
    PolygonMotionEvaluator,
    YoloRoiDisplacementTracker,
)
from recorder import ClipRecorder
from utilization_tracker import UtilizationTracker
from offline_session_tracker import OfflineSessionTracker
from select_roi_rtsp import channel_key_from_url, cam_ip_from_url
from rtsp_reader import RtspStreamReader
from ws_client import LiveWebSocketClient

OBSERVATION_STALE_SECONDS = 3.0
RESOLVER_TICK_SECONDS = 1.0


def draw_roi_annotation(frame, roi, final_label, confidence, extra_text="", tracker=None):
    # Match detection.py colors: Green for running, Red for stopped/idle
    color = (0, 255, 0) if final_label == "running" else (0, 0, 255)
    machine_id = roi["machine_id"]

    if roi.get("shape") == "polygon":
        pts = np.array(roi["points"], dtype=np.int32)
        if len(pts) >= 3:
            # 1. Semi-transparent polygon fill (matching detection.py)
            overlay = frame.copy()
            cv2.fillPoly(overlay, [pts], color)
            cv2.addWeighted(overlay, 0.20, frame, 0.80, 0, frame)

            # 2. Border outline (thickness=3 matching detection.py)
            cv2.polylines(frame, [pts], isClosed=True, color=color, thickness=3)

            # 3. Directional Motion Vector Arrow inside Polygon if moving >= min_displacement_meters
            if tracker and tracker.curr_centroid and tracker.prev_centroid and tracker.last_displacement_meters >= tracker.min_displacement_meters:
                p1 = (int(tracker.prev_centroid[0]), int(tracker.prev_centroid[1]))
                p2 = (int(tracker.curr_centroid[0]), int(tracker.curr_centroid[1]))
                cv2.arrowedLine(frame, p1, p2, (255, 255, 0), 3, tipLength=0.3)
                cv2.circle(frame, p2, 6, (0, 255, 255), -1)

            # 4. Centered Badge inside Polygon (matching detection.py)
            M = cv2.moments(pts)
            if M["m00"] != 0:
                cx = int(M["m10"] / M["m00"])
                cy = int(M["m01"] / M["m00"])
            else:
                cx, cy = pts[0][0], pts[0][1]

            dir_str = tracker.last_direction if tracker else "STATIONARY"
            disp_m = tracker.last_displacement_meters if tracker else 0.0
            status_tag = f"RUNNING ({dir_str})" if final_label == "running" else f"IDLE ({dir_str})"
            label_str = f"{machine_id}: {status_tag} [{disp_m:.2f}m]"
            if not tracker and extra_text:
                label_str = f"{machine_id}: {final_label.upper()} ({extra_text})"

            (txt_w, txt_h), _ = cv2.getTextSize(label_str, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
            cv2.rectangle(frame, (cx - txt_w // 2 - 6, cy - txt_h // 2 - 6),
                          (cx + txt_w // 2 + 6, cy + txt_h // 2 + 6), (0, 0, 0), -1)
            cv2.rectangle(frame, (cx - txt_w // 2 - 6, cy - txt_h // 2 - 6),
                          (cx + txt_w // 2 + 6, cy + txt_h // 2 + 6), color, 2)
            cv2.putText(frame, label_str, (cx - txt_w // 2, cy + txt_h // 2 - 2),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
            return

    # Fallback for bbox
    x, y, w, h = roi.get("bbox", (0, 0, 50, 50))
    cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)
    label_x, label_y = x, max(y - 10, 20)
    label = f"{machine_id}: {final_label.upper()}"
    if extra_text:
        label += f" ({extra_text})"
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
    """Update camera's status in the shared dict with a timestamp."""
    try:
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
    except Exception:
        pass


def camera_pipeline(url, stop_event, shared_observations, shared_camera_status):
    def handle_sigterm(signum, frame):
        raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM, handle_sigterm)

    channel_key = channel_key_from_url(url)
    cam_ip = cam_ip_from_url(url)

    roi_manager = ROIManager(config.ROI_CONFIG_PATH, valid_machine_ids=config.MACHINE_IDS)
    rois = roi_manager.all_config.get(channel_key, [])
    if not rois:
        print(f"[{channel_key}] No ROI configured in {config.ROI_CONFIG_PATH}. Exiting this worker.")
        set_camera_status(shared_camera_status, channel_key, cam_ip, "no_roi_configured")
        return

    print(f"[{channel_key}] Initializing pipeline for {len(rois)} machine(s): {[r['machine_id'] for r in rois]}")

    # Initialize tracking engines per machine in this camera
    motion_evaluators = {}
    yolo_trackers = {}
    has_yolo_machines = False

    for roi in rois:
        m_id = roi["machine_id"]
        points = roi.get("points") or roi.get("bbox")
        if roi.get("shape") == "polygon":
            pts = np.array(points, dtype=np.int32)
        else:
            x, y, w, h = points
            pts = np.array([[x, y], [x + w, y], [x + w, y + h], [x, y + h]], dtype=np.int32)

        if m_id == "MC-001":
            # MC-001: Polygon-masked frame differencing motion detector
            motion_evaluators[m_id] = PolygonMotionEvaluator(
                pts,
                pixel_threshold=config.MC001_MOTION_PIXEL_THRESHOLD,
                diff_threshold=config.MC001_DIFF_THRESHOLD,
            )
            print(f"[{channel_key}] Initialized PolygonMotionEvaluator for {m_id}")
        else:
            # MC-002 .. MC-006: YOLO detection & centroid displacement tracker (detection.py logic)
            yolo_trackers[m_id] = YoloRoiDisplacementTracker(
                pts,
                pixels_per_meter=config.PIXELS_PER_METER,
                min_displacement_meters=config.MIN_DISPLACEMENT_METERS,
                history_len=config.DISPLACEMENT_WINDOW_FRAMES,
                movement_window_len=getattr(config, "MOVEMENT_WINDOW_1M_FRAMES", 300),
            )
            has_yolo_machines = True
            print(f"[{channel_key}] Initialized YoloRoiDisplacementTracker for {m_id}")

    # Load YOLO Model if any machine uses YOLO detection
    model = None
    if has_yolo_machines:
        print(f"[{channel_key}] Loading YOLO model from {config.MODEL_PATH}...")
        model = YOLO(config.MODEL_PATH)
        print(f"[{channel_key}] YOLO Model loaded successfully.")

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

    offline_tracker = OfflineSessionTracker(config.API_BASE_URL)
    session_state = {"offline_since": None}

    def on_connect():
        print(f"[{channel_key}] Connected to stream.")
        set_camera_status(shared_camera_status, channel_key, cam_ip, "online")
        if session_state["offline_since"] is not None:
            offline_tracker.mark_online(channel_key, cam_ip, session_state["offline_since"])
            session_state["offline_since"] = None

    def on_disconnect():
        print(f"[{channel_key}] Lost stream connection - recovering...")
        set_camera_status(shared_camera_status, channel_key, cam_ip, "offline")
        if session_state["offline_since"] is None:
            session_state["offline_since"] = time.time()
            offline_tracker.mark_offline(channel_key, cam_ip, session_state["offline_since"])
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
    print(f"[{channel_key}] Detection & Tracking loop running.")

    try:
        while not stop_event.is_set():
            raw_frame = reader.read()

            if raw_frame is None:
                time.sleep(0.04)
                continue

            set_camera_status(shared_camera_status, channel_key, cam_ip, "online")

            # 1. Run YOLO Object Detection once per frame if needed
            detection_boxes = []
            detection_confs = []

            if has_yolo_machines and model is not None:
                results = model.predict(
                    raw_frame,
                    conf=config.YOLO_CONF_THRESHOLD,
                    iou=config.YOLO_IOU_THRESHOLD,
                    verbose=False
                )[0]
                if results.boxes is not None and len(results.boxes) > 0:
                    detection_boxes = results.boxes.xyxy.cpu().numpy()
                    detection_confs = results.boxes.conf.cpu().numpy()

            annotated_frame = raw_frame.copy()

            # 2. Evaluate Each Machine ROI
            for roi in rois:
                machine_id = roi["machine_id"]
                raw_label = "stopped"
                confidence = 50.0
                extra_text = ""
                tracker = None

                if machine_id == "MC-001" and machine_id in motion_evaluators:
                    # MC-001: Polygon Frame Differencing
                    raw_label, px_count, confidence = motion_evaluators[machine_id].evaluate(raw_frame)
                    extra_text = f"{px_count}px"
                elif machine_id in yolo_trackers:
                    # MC-002 .. MC-006: YOLO Object Detection + Centroid Displacement
                    tracker = yolo_trackers[machine_id]
                    raw_label, disp_m, confidence = tracker.match_and_update(
                        detection_boxes, detection_confs
                    )
                    dir_str = tracker.last_direction
                    extra_text = f"{disp_m:.2f}m {dir_str}"

                # Majority-vote smoothing
                smoothed_label = smoother.smooth(channel_key, machine_id, raw_label)
                final_label = smoothed_label

                # Draw ROI overlay on annotated frame (using detection.py style overlays)
                draw_roi_annotation(annotated_frame, roi, final_label, confidence, extra_text, tracker=tracker)

                # Share observation with resolver
                try:
                    shared_observations[(machine_id, channel_key)] = (final_label, confidence, time.time())
                except Exception:
                    pass

                # Trigger ClipRecorder on state changes
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

    try:
        obs_items = list(shared_observations.items())
    except Exception:
        obs_items = []

    for machine_id in machine_ids:
        best_label = None
        best_confidence = -1
        has_fresh_signal = False

        for (obs_machine_id, channel_key), (label, confidence, timestamp) in obs_items:
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
        else:
            resolved[machine_id] = best_label if best_label is not None else "uncertain"

    return resolved


def write_camera_log(shared_camera_status):
    try:
        data = dict(shared_camera_status)
        with open(config.CAMERA_LOG_PATH, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"[CAMERA LOG ERROR] {e}")


def get_all_configured_machine_ids():
    with open(config.ROI_CONFIG_PATH, "r") as f:
        roi_config = json.load(f)
    active_channel_keys = {channel_key_from_url(url) for url in config.RTSP_URLS}
    machine_ids = set()
    for channel_key, channel_rois in roi_config.items():
        if channel_key in active_channel_keys:
            for roi in channel_rois:
                machine_ids.add(roi["machine_id"])
    return sorted(machine_ids)


def get_machine_to_channels_map():
    with open(config.ROI_CONFIG_PATH, "r") as f:
        roi_config = json.load(f)
    active_channel_keys = {channel_key_from_url(url) for url in config.RTSP_URLS}
    mapping = {}
    for channel_key, rois in roi_config.items():
        if channel_key in active_channel_keys:
            for roi in rois:
                mapping.setdefault(roi["machine_id"], []).append(channel_key)
    return mapping


def update_camera_status_for_machines(shared_camera_status, machine_to_channels):
    now_iso = datetime.now().astimezone().isoformat()

    for machine_id, channels in machine_to_channels.items():
        try:
            is_online = any(
                shared_camera_status.get(ch, {}).get("status") == "online"
                for ch in channels
            )
        except Exception:
            is_online = False

        new_status = "online" if is_online else "offline"
        patch_payload = {"camera_status": new_status}
        if is_online:
            patch_payload["detected_at"] = now_iso

        try:
            requests.patch(
                f"{config.API_BASE_URL}/api/machines/{machine_id}",
                json=patch_payload,
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
    print(f"Tracking {len(machine_ids)} machine(s) across {len(config.RTSP_URLS)} active cameras: {machine_ids}")

    processes = []
    for url in config.RTSP_URLS:
        p = multiprocessing.Process(
            target=camera_pipeline,
            args=(url, stop_event, shared_observations, shared_camera_status),
            daemon=True
        )
        p.start()
        processes.append(p)

    tracker = UtilizationTracker(
        config.UTILIZATION_STATE_PATH,
        config.UTILIZATION_LOG_PATH,
        api_base_url=config.API_BASE_URL,
        undetected_log_path=config.UNDETECTED_LOG_PATH
    )
    last_sync_time = time.time()
    last_camera_log_time = time.time()

    ws_client = LiveWebSocketClient(config.API_BASE_URL)
    ws_client.start()

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

            # Transmit real-time telemetry snapshot over WebSocket
            today_str = tracker._today_str()
            live_machines = {}
            for m_id in machine_ids:
                r_run, r_down, r_off, r_undet, r_avail, r_util = tracker.get_summary(today_str, m_id)
                live_machines[m_id] = {
                    "status": resolved.get(m_id, "offline"),
                    "runtime": round(r_run, 2),
                    "downtime": round(r_down, 2),
                    "total_available_time": round(r_avail, 2),
                    "utilization_percent": round(r_util, 2),
                }

            ws_payload = {
                "type": "live_update",
                "timestamp": datetime.now().astimezone().isoformat(),
                "machines": live_machines,
                "cameras": dict(shared_camera_status),
            }
            ws_client.send_live_data(ws_payload)

            if time.time() - last_sync_time >= config.UTILIZATION_SYNC_INTERVAL_SECONDS:
                tracker.write_all_logs()
                last_sync_time = time.time()

            if time.time() - last_camera_log_time >= config.CAMERA_LOG_WRITE_INTERVAL_SECONDS:
                write_camera_log(shared_camera_status)
                update_camera_status_for_machines(shared_camera_status, machine_to_channels)
                last_camera_log_time = time.time()

    except KeyboardInterrupt:
        print("Stopping all camera processes...")
        stop_event.set()
        for p in processes:
            p.join(timeout=10)
        try:
            tracker.write_all_logs()
            write_camera_log(shared_camera_status)
        except Exception:
            pass
        ws_client.stop()
        print("All cameras stopped cleanly.")


if __name__ == "__main__":
    main()
