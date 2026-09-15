import cv2
import numpy as np
import time
import json
import os
import sys
import math
from collections import deque
from datetime import datetime, timedelta

# Ensure factory_analytics directory is in sys.path for rtsp_reader
ANALYTICS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "factory_analytics")
if ANALYTICS_DIR not in sys.path:
    sys.path.insert(0, ANALYTICS_DIR)

import supervision as sv
from ultralytics import YOLO
from rtsp_reader import RtspStreamReader

# Configuration
RTSP_URL_1 = r"rtsp://admin:admin@123@103.57.247.234:554/cam/realmonitor?channel=23&subtype=1"
RTSP_URL_2 = r"rtsp://admin:admin@123@103.57.247.234:554/cam/realmonitor?channel=24&subtype=1"

# Resolve model path (check hardcoded path, fall back to local directory)
LOCAL_MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "best (5).pt")
DEFAULT_MODEL_PATH = r"D:\RTSP-READER\RTSP-READER\best (2)\best (5).pt"
MODEL_PATH = DEFAULT_MODEL_PATH if os.path.exists(DEFAULT_MODEL_PATH) else LOCAL_MODEL_PATH

POLYGON_CONFIG_FILE = "polygon_config.json"
UTILIZATION_LOG_FILE = "machine_utilization_log.json"

CHECK_INTERVAL_SECONDS = 60  # Evaluate status & log utilization every 1 minute (60 seconds)
WINDOW_24H_SECONDS = 86400    # 24 Hours in seconds
PIXELS_PER_METER = 50.0       # Pixel calibration scale factor (50 pixels = 1.0 meter)
MIN_DISPLACEMENT_METERS = 1.0 # Minimum movement threshold required (1.0 meter in any direction)

class MultiMachineYoloDetector:
    active_instance = None
    all_instances = []

    def __init__(self, rtsp_url=RTSP_URL_1, model=None, model_path=MODEL_PATH, window_name="Camera 1", 
                 polygon_config_file="polygon_config_cam1.json", conf_threshold=0.35, iou_threshold=0.35,
                 check_interval=CHECK_INTERVAL_SECONDS, min_displacement_meters=MIN_DISPLACEMENT_METERS,
                 pixels_per_meter=PIXELS_PER_METER):
        """
        Multi-Machine Directional Motion & 1-Meter Utilization Tracker:
        - Supports single or multi-camera setups with separate windows.
        - Tracks bounding box displacement (dx, dy) in meters inside machine polygon ROIs.
        - Classifies machine as 'active_machine' (Running) ONLY if box moves at least 1.0 meter in any direction.
        - Computes 24-Hour Utilization % and logs to machine_utilization_log.json every 1 minute.
        """
        MultiMachineYoloDetector.all_instances.append(self)

        self.rtsp_url = rtsp_url
        self.model_path = model_path
        self.window_name = window_name
        self.polygon_config_file = polygon_config_file
        self.conf_threshold = conf_threshold
        self.iou_threshold = iou_threshold
        self.check_interval = check_interval
        self.min_displacement_meters = min_displacement_meters
        self.pixels_per_meter = pixels_per_meter

        # Load or use shared YOLO Model
        if model is not None:
            self.model = model
        else:
            print(f"[{self.window_name}] Loading YOLO model from '{self.model_path}'...")
            self.model = YOLO(self.model_path)
            print(f"[{self.window_name}] Model loaded successfully! Classes: {self.model.names}")

        # Initialize Supervision Corner Box & Label Annotators (thickness=3, corner_length=10)
        self.corner_annotator = sv.BoxCornerAnnotator(thickness=3, corner_length=10)
        self.label_annotator = sv.LabelAnnotator()

        self.machines = {}
        self.drawing_points = []
        self.current_hover_pos = None
        self.is_drawing = False

        self.reader = None
        self.last_eval_time = time.time()

        # Load saved polygon config & existing utilization log
        self._load_polygon_config()
        self._load_existing_utilization_log()

        self.active_drawing_name = self._get_next_machine_name()

    def _get_next_machine_name(self):
        """Generates continuous global machine tags (Machine_1, Machine_2, Machine_3...) across all camera instances."""
        existing_names = set()
        for inst in MultiMachineYoloDetector.all_instances:
            existing_names.update(inst.machines.keys())

        count = 1
        while f"Machine_{count}" in existing_names:
            count += 1
        return f"Machine_{count}"

    def _load_polygon_config(self):
        """Loads polygon coordinates from polygon_config_file."""
        if not os.path.exists(self.polygon_config_file):
            return
        try:
            with open(self.polygon_config_file, "r") as f:
                data = json.load(f)
            machines_data = data.get("machines", {})
            for m_name, m_info in machines_data.items():
                pts = [tuple(p) for p in m_info.get("polygon_points", [])]
                if len(pts) >= 3:
                    self.machines[m_name] = {
                        "points": pts,
                        "centroid_history": deque(maxlen=15),
                        "movement_history_1m": deque(maxlen=300),
                        "current_status": "inactive_machine",
                        "last_displacement_px": 0.0,
                        "last_displacement_meters": 0.0,
                        "last_direction": "STATIONARY",
                        "curr_centroid": None,
                        "prev_centroid": None,
                        "last_checked": datetime.now().isoformat(timespec='seconds'),
                        "history_24h": []
                    }
            print(f"[{self.window_name}] Loaded {len(self.machines)} machine ROI(s) from {self.polygon_config_file}")
            self.active_drawing_name = self._get_next_machine_name()
        except Exception as e:
            print(f"[{self.window_name}] Error loading polygon config: {e}")

    def _load_existing_utilization_log(self):
        """Reconstruct 24-hour event history from machine_utilization_log.json if present."""
        if not os.path.exists(UTILIZATION_LOG_FILE):
            return
        try:
            with open(UTILIZATION_LOG_FILE, "r") as f:
                data = json.load(f)
            
            now_epoch = time.time()
            cutoff = now_epoch - WINDOW_24H_SECONDS
            machines_data = data.get("machines", {})

            for m_name, m_info in machines_data.items():
                if m_name in self.machines:
                    self.machines[m_name]["current_status"] = m_info.get("current_status", "inactive_machine")
                    recent_events = m_info.get("recent_events", [])
                    
                    for ev in recent_events:
                        ts_str = ev.get("timestamp")
                        status = ev.get("status")
                        if ts_str and status:
                            try:
                                dt = datetime.fromisoformat(ts_str)
                                epoch = dt.timestamp()
                                if epoch >= cutoff:
                                    self.machines[m_name]["history_24h"].append({"epoch": epoch, "status": status})
                            except ValueError:
                                pass
        except Exception as e:
            print(f"[YOLO Detector] Warning loading utilization log: {e}")

    def save_polygon_config(self):
        """Saves tagged machine polygon coordinates to polygon_config_file."""
        machines_data = {
            m_name: {"polygon_points": [list(p) for p in m_info["points"]]}
            for m_name, m_info in self.machines.items()
        }
        output_data = {
            "total_machines": len(self.machines),
            "machines": machines_data
        }
        try:
            with open(self.polygon_config_file, "w") as f:
                json.dump(output_data, f, indent=2)
            print(f"[{self.window_name}] Saved {len(self.machines)} machine polygon(s) to {self.polygon_config_file}")
        except Exception as e:
            print(f"[{self.window_name}] Error saving polygon config: {e}")

    def _mouse_callback(self, event, x, y, flags, param):
        """Interactive mouse callback for drawing machine polygon points."""
        MultiMachineYoloDetector.active_instance = self
        self.current_hover_pos = (x, y)

        if event == cv2.EVENT_LBUTTONDOWN:
            self.is_drawing = True
            self.drawing_points.append((x, y))
            print(f"[{self.active_drawing_name}] Added Point {len(self.drawing_points)}: ({x}, {y})")

        elif event == cv2.EVENT_RBUTTONDOWN:
            self.finish_current_machine()

    def finish_current_machine(self):
        """Completes drawing for active machine tag."""
        if len(self.drawing_points) >= 3:
            m_name = self.active_drawing_name
            self.machines[m_name] = {
                "points": list(self.drawing_points),
                "centroid_history": deque(maxlen=15),
                "movement_history_1m": deque(maxlen=300),
                "current_status": "inactive_machine",
                "last_displacement_px": 0.0,
                "last_direction": "STATIONARY",
                "curr_centroid": None,
                "prev_centroid": None,
                "last_checked": datetime.now().isoformat(timespec='seconds'),
                "history_24h": []
            }
            print(f"[{self.window_name}] Saved '{m_name}' with {len(self.drawing_points)} points!")

            self.drawing_points = []
            self.is_drawing = False
            self.save_polygon_config()

            for inst in MultiMachineYoloDetector.all_instances:
                inst.active_drawing_name = inst._get_next_machine_name()
            print(f"[{self.window_name}] Next machine ready: Click points for '{self.active_drawing_name}'.")
        else:
            print(f"[{self.window_name}] Need at least 3 points to complete polygon ROI.")

    def match_detection_to_machine(self, xyxy):
        """Finds which machine polygon ROI contains the detected object center."""
        x1, y1, x2, y2 = xyxy
        cx = (x1 + x2) / 2.0
        cy = (y1 + y2) / 2.0

        for m_name, m_info in self.machines.items():
            pts_list = m_info["points"]
            if len(pts_list) >= 3:
                pts = np.array(pts_list, dtype=np.int32)
                if cv2.pointPolygonTest(pts, (cx, cy), False) >= 0:
                    return m_name, (cx, cy)
        return None, (cx, cy)

    def calculate_direction(self, dx, dy):
        """Determines directional movement string based on dx, dy displacement vectors."""
        abs_dx, abs_dy = abs(dx), abs(dy)
        if abs_dx < 2.0 and abs_dy < 2.0:
            return "STATIONARY"
        
        if abs_dx > 1.8 * abs_dy:
            return "RIGHT ->" if dx > 0 else "LEFT <-"
        elif abs_dy > 1.8 * abs_dx:
            return "DOWN v" if dy > 0 else "UP ^"
        else:
            if dx > 0 and dy > 0:
                return "DOWN-RIGHT ->"
            elif dx > 0 and dy < 0:
                return "UP-RIGHT ->"
            elif dx < 0 and dy > 0:
                return "DOWN-LEFT <-"
            else:
                return "UP-LEFT <-"

    def process_detections(self, detections):
        """
        Tracks centroid spatial displacement (dx, dy) in meters inside each machine ROI polygon.
        Machine is marked active ONLY if box moves at least 1.0 meter (min_displacement_meters).
        """
        machine_centroids = {m_name: [] for m_name in self.machines}

        if detections is not None and len(detections) > 0:
            for xyxy in detections.xyxy:
                m_name, (cx, cy) = self.match_detection_to_machine(xyxy)
                if m_name and m_name in machine_centroids:
                    machine_centroids[m_name].append((cx, cy))

        for m_name, centroids in machine_centroids.items():
            m_info = self.machines[m_name]
            
            if centroids:
                # Use average centroid if multiple objects detected in same ROI
                avg_cx = sum(c[0] for c in centroids) / len(centroids)
                avg_cy = sum(c[1] for c in centroids) / len(centroids)
                curr_pos = (avg_cx, avg_cy)
                
                m_info["centroid_history"].append(curr_pos)
                m_info["curr_centroid"] = curr_pos

                # Calculate displacement in meters against centroid from 5 frames ago
                if len(m_info["centroid_history"]) >= 4:
                    prev_pos = m_info["centroid_history"][0]
                    m_info["prev_centroid"] = prev_pos

                    dx = curr_pos[0] - prev_pos[0]
                    dy = curr_pos[1] - prev_pos[1]
                    displacement_px = math.hypot(dx, dy)
                    displacement_m = displacement_px / self.pixels_per_meter

                    m_info["last_displacement_meters"] = round(displacement_m, 2)
                    m_info["last_displacement_px"] = round(displacement_px, 1)
                    m_info["last_direction"] = self.calculate_direction(dx, dy)
                    m_info["movement_history_1m"].append(displacement_m)
                else:
                    m_info["movement_history_1m"].append(0.0)
            else:
                m_info["movement_history_1m"].append(0.0)
                m_info["last_displacement_meters"] = 0.0
                m_info["last_displacement_px"] = 0.0
                m_info["last_direction"] = "NO OBJECT"
                m_info["curr_centroid"] = None
                m_info["prev_centroid"] = None

            # LIVE STATUS UPDATE:
            # Machine is ACTIVE (Running) ONLY if recent centroid displacement >= min_displacement_meters (1.0m)
            max_recent_displacement_m = max(m_info["movement_history_1m"]) if m_info["movement_history_1m"] else 0.0
            if max_recent_displacement_m >= self.min_displacement_meters:
                m_info["current_status"] = "active_machine"
            else:
                m_info["current_status"] = "inactive_machine"

        # Trigger 1-Minute Periodic Evaluation & Utilization Log Update
        now_epoch = time.time()
        if now_epoch - self.last_eval_time >= self.check_interval:
            self.evaluate_and_log_utilization()
            self.last_eval_time = now_epoch

    def evaluate_and_log_utilization(self):
        """
        Evaluates machine activity every 1 minute (60s) based on 1-meter displacement threshold
        and updates machine_utilization_log.json.
        """
        now_epoch = time.time()
        now_iso = datetime.now().isoformat(timespec='seconds')
        cutoff = now_epoch - WINDOW_24H_SECONDS

        log_output = {
            "last_updated": now_iso,
            "tracking_period": "24_hours",
            "check_interval_seconds": self.check_interval,
            "pixels_per_meter": self.pixels_per_meter,
            "min_displacement_meters": self.min_displacement_meters,
            "summary": {
                "total_machines": len(self.machines),
                "active_machines": sum(1 for m in self.machines.values() if m["current_status"] == "active_machine"),
                "inactive_machines": sum(1 for m in self.machines.values() if m["current_status"] == "inactive_machine")
            },
            "machines": {}
        }

        for m_name, m_info in self.machines.items():
            hist_1m = m_info["movement_history_1m"]
            max_displacement_1m_m = max(hist_1m) if hist_1m else 0.0
            
            # Machine is ACTIVE only if box moved >= min_displacement_meters (1.0m) during 1-minute window
            new_status = "active_machine" if max_displacement_1m_m >= self.min_displacement_meters else "inactive_machine"
            m_info["current_status"] = new_status
            m_info["last_checked"] = now_iso

            # Record event if status changed or history is empty
            hist_24h = m_info["history_24h"]
            if not hist_24h or hist_24h[-1]["status"] != new_status:
                hist_24h.append({"epoch": now_epoch, "status": new_status})

            # Trim 24-hour history
            m_info["history_24h"] = [ev for ev in hist_24h if ev["epoch"] >= cutoff]

            # Calculate 24-hour utilization analytics
            util_metrics = self._calculate_24h_utilization(m_name, now_epoch)

            recent_events = [
                {
                    "timestamp": datetime.fromtimestamp(ev["epoch"]).isoformat(timespec='seconds'),
                    "status": ev["status"]
                }
                for ev in m_info["history_24h"][-50:]
            ]

            log_output["machines"][m_name] = {
                "current_status": new_status,
                "last_checked": now_iso,
                "max_displacement_1m_meters": round(max_displacement_1m_m, 2),
                "last_direction": m_info.get("last_direction", "STATIONARY"),
                "utilization_24h": util_metrics,
                "recent_events": recent_events
            }

        # Save to JSON file atomically
        temp_file = f"{UTILIZATION_LOG_FILE}.tmp"
        with open(temp_file, "w") as f:
            json.dump(log_output, f, indent=2)
        os.replace(temp_file, UTILIZATION_LOG_FILE)

        print(f"[{datetime.now().strftime('%H:%M:%S')}] Evaluated 1-meter movement threshold. Updated {UTILIZATION_LOG_FILE}")
        return log_output

    def _calculate_24h_utilization(self, machine_name, now_epoch):
        """Calculates active vs inactive duration and Utilization % over 24 hours."""
        events = self.machines[machine_name]["history_24h"]
        cutoff_epoch = now_epoch - WINDOW_24H_SECONDS

        if not events:
            return {
                "active_seconds": 0.0,
                "inactive_seconds": 0.0,
                "active_formatted": "00h 00m 00s",
                "inactive_formatted": "00h 00m 00s",
                "utilization_percentage": 0.0,
                "active_event_count": 0,
                "inactive_event_count": 0
            }

        sorted_events = sorted(events, key=lambda x: x["epoch"])
        start_time = max(cutoff_epoch, sorted_events[0]["epoch"])

        active_seconds = 0.0
        inactive_seconds = 0.0
        active_count = 0
        inactive_count = 0

        current_status = sorted_events[0]["status"]
        last_t = start_time

        for ev in sorted_events:
            ev_t = max(cutoff_epoch, ev["epoch"])
            duration = max(0.0, ev_t - last_t)

            if current_status == "active_machine":
                active_seconds += duration
            else:
                inactive_seconds += duration

            if ev["status"] == "active_machine":
                active_count += 1
            elif ev["status"] == "inactive_machine":
                inactive_count += 1

            current_status = ev["status"]
            last_t = ev_t

        final_duration = max(0.0, now_epoch - last_t)
        if current_status == "active_machine":
            active_seconds += final_duration
        else:
            inactive_seconds += final_duration

        total_tracked = active_seconds + inactive_seconds
        util_pct = (active_seconds / total_tracked * 100.0) if total_tracked > 0 else 0.0

        return {
            "active_seconds": round(active_seconds, 1),
            "inactive_seconds": round(inactive_seconds, 1),
            "active_formatted": self._format_seconds(active_seconds),
            "inactive_formatted": self._format_seconds(inactive_seconds),
            "utilization_percentage": round(util_pct, 2),
            "active_event_count": active_count,
            "inactive_event_count": inactive_count
        }

    @staticmethod
    def _format_seconds(seconds):
        sec = int(seconds)
        hours = sec // 3600
        minutes = (sec % 3600) // 60
        secs = sec % 60
        return f"{hours:02d}h {minutes:02d}m {secs:02d}s"

    def draw_overlays(self, frame, detections, labels):
        h, w = frame.shape[:2]
        output = frame.copy()
        now_epoch = time.time()

        active_machines_count = sum(1 for m in self.machines.values() if m["current_status"] == "active_machine")
        total_machines_count = len(self.machines)

        # 1. Render Semi-Transparent Machine Polygons, Motion Arrows & Badges
        for m_name, m_info in self.machines.items():
            pts_list = m_info["points"]
            status = m_info["current_status"]
            disp_px = m_info.get("last_displacement_px", 0.0)
            disp_m = m_info.get("last_displacement_meters", 0.0)
            direction = m_info.get("last_direction", "STATIONARY")
            
            metrics = self._calculate_24h_utilization(m_name, now_epoch)
            util_pct = metrics["utilization_percentage"]

            if status == "active_machine":
                theme_color = (0, 255, 0) # Green
                status_tag = f"RUNNING ({direction})"
            else:
                theme_color = (0, 0, 255) # Red
                status_tag = f"IDLE ({direction})"

            if len(pts_list) >= 3:
                pts = np.array(pts_list, dtype=np.int32)
                
                # Semi-transparent polygon fill
                overlay = output.copy()
                cv2.fillPoly(overlay, [pts], theme_color)
                cv2.addWeighted(overlay, 0.20, output, 0.80, 0, output)

                # Border outline
                cv2.polylines(output, [pts], isClosed=True, color=theme_color, thickness=3)

                # Draw Directional Motion Vector Arrow inside Polygon if moving >= min_displacement_meters (1.0m)
                curr_c = m_info.get("curr_centroid")
                prev_c = m_info.get("prev_centroid")
                if curr_c and prev_c and disp_m >= self.min_displacement_meters:
                    p1 = (int(prev_c[0]), int(prev_c[1]))
                    p2 = (int(curr_c[0]), int(curr_c[1]))
                    cv2.arrowedLine(output, p1, p2, (255, 255, 0), 3, tipLength=0.3)
                    cv2.circle(output, p2, 6, (0, 255, 255), -1)

                # Centered Badge inside Polygon
                M = cv2.moments(pts)
                if M["m00"] != 0:
                    cx = int(M["m10"] / M["m00"])
                    cy = int(M["m01"] / M["m00"])
                else:
                    cx, cy = pts[0][0], pts[0][1]

                label_str = f"{m_name}: {status_tag} [{disp_m:.2f}m]"
                (txt_w, txt_h), _ = cv2.getTextSize(label_str, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)

                cv2.rectangle(output, (cx - txt_w // 2 - 6, cy - txt_h // 2 - 6),
                              (cx + txt_w // 2 + 6, cy + txt_h // 2 + 6), (0, 0, 0), -1)
                cv2.rectangle(output, (cx - txt_w // 2 - 6, cy - txt_h // 2 - 6),
                              (cx + txt_w // 2 + 6, cy + txt_h // 2 + 6), theme_color, 2)
                cv2.putText(output, label_str, (cx - txt_w // 2, cy + txt_h // 2 - 2),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

        # 2. Render Supervision Corner Bounding Boxes & Labels
        if detections is not None and len(detections) > 0:
            output = self.corner_annotator.annotate(scene=output, detections=detections)
            output = self.label_annotator.annotate(scene=output, detections=detections, labels=labels)

        # 3. Live User Drawing Feedback
        if self.drawing_points:
            for i in range(len(self.drawing_points) - 1):
                cv2.line(output, self.drawing_points[i], self.drawing_points[i+1], (0, 255, 255), 2)
            if self.current_hover_pos:
                cv2.line(output, self.drawing_points[-1], self.current_hover_pos, (255, 255, 0), 1, cv2.LINE_AA)
            for i, p in enumerate(self.drawing_points):
                cv2.circle(output, p, 6, (0, 255, 255), -1)
                cv2.putText(output, f"{self.active_drawing_name}-P{i+1}", (p[0] + 8, p[1] - 8),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 2)

        # 4. Top-Left HUD Summary Panel
        is_focused = (MultiMachineYoloDetector.active_instance == self)
        focus_tag = " [ACTIVE FOCUS]" if is_focused else ""
        border_col = (0, 255, 0) if is_focused else (100, 100, 100)

        hud_h = 55 + max(1, total_machines_count) * 28
        cv2.rectangle(output, (15, 15), (480, 15 + hud_h), (0, 0, 0), -1)
        cv2.rectangle(output, (15, 15), (480, 15 + hud_h), border_col, 1)

        cv2.putText(output, f"DIRECTIONAL MOTION TRACKER{focus_tag}", (25, 35), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.48, (0, 255, 255) if is_focused else (180, 180, 180), 2)
        cv2.putText(output, f"Active Machines: {active_machines_count}/{total_machines_count}", (25, 55), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)

        y_offset = 80
        for m_name, m_info in self.machines.items():
            st = m_info["current_status"]
            col = (0, 255, 0) if st == "active_machine" else (0, 0, 255)
            metrics = self._calculate_24h_utilization(m_name, now_epoch)
            disp_m = m_info.get("last_displacement_meters", 0.0)
            dir_str = m_info.get("last_direction", "STATIONARY")
            line_str = f"{m_name}: {'RUNNING' if st=='active_machine' else 'IDLE'} | {dir_str} ({disp_m:.2f}m) | Util: {metrics['utilization_percentage']:.1f}%"
            cv2.putText(output, line_str, (25, y_offset), cv2.FONT_HERSHEY_SIMPLEX, 0.42, col, 1)
            y_offset += 28

        # Footer controls
        cv2.putText(output, f"[Left Click]: Draw ROI | [Right Click/Enter]: Finish '{self.active_drawing_name}' | [+ / -]: Meter Threshold", 
                    (15, h - 15), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (200, 200, 200), 1)

        return output

    def process_and_show_frame(self, frame):
        """Processes one frame for this camera instance and displays in its OpenCV window."""
        results = self.model.predict(frame, conf=self.conf_threshold, iou=self.iou_threshold, verbose=False)[0]
        detections = sv.Detections.from_ultralytics(results)

        self.process_detections(detections)

        labels = []
        if detections is not None and len(detections) > 0:
            for xyxy, confidence, class_id in zip(detections.xyxy, detections.confidence, detections.class_id):
                cls_name = self.model.names[class_id]
                m_name, _ = self.match_detection_to_machine(xyxy)
                tag = f"[{m_name}] " if m_name else ""
                labels.append(f"{tag}{cls_name} {confidence:.2f}")

        annotated_frame = self.draw_overlays(frame, detections, labels)
        cv2.imshow(self.window_name, annotated_frame)

    def handle_key(self, key):
        """Handles keyboard events for this camera instance."""
        if key == 13 or key == ord('f'):
            self.finish_current_machine()
        elif key == ord('e'):
            self.evaluate_and_log_utilization()
        elif key == ord('n'):
            self.drawing_points = []
            for inst in MultiMachineYoloDetector.all_instances:
                inst.active_drawing_name = inst._get_next_machine_name()
            print(f"[{self.window_name}] Ready to draw {self.active_drawing_name}")
        elif key == ord('c'):
            self.machines = {}
            self.drawing_points = []
            self.save_polygon_config()
            for inst in MultiMachineYoloDetector.all_instances:
                inst.active_drawing_name = inst._get_next_machine_name()
            print(f"[{self.window_name}] All machine ROIs cleared.")
        elif key == ord('s'):
            self.save_polygon_config()
        elif key == ord('+') or key == ord('='):
            self.min_displacement_meters += 0.25
            print(f"[{self.window_name}] Min displacement threshold: {self.min_displacement_meters:.2f}m")
        elif key == ord('-') or key == ord('_'):
            self.min_displacement_meters = max(0.10, self.min_displacement_meters - 0.25)
            print(f"[{self.window_name}] Min displacement threshold: {self.min_displacement_meters:.2f}m")


def main():
    print("=" * 60)
    print("  MULTI-CAMERA YOLO DETECTION & UTILIZATION TRACKER")
    print("=" * 60)
    
    print(f"Loading shared YOLO model '{MODEL_PATH}'...")
    shared_model = YOLO(MODEL_PATH)
    print(f"Model loaded successfully! Classes: {shared_model.names}\n")

    # Camera 1 (Channel 23)
    cam1 = MultiMachineYoloDetector(
        rtsp_url=RTSP_URL_1,
        model=shared_model,
        window_name="Camera 1 (Channel 23)",
        polygon_config_file="polygon_config_cam1.json"
    )

    # Camera 2 (Channel 24)
    cam2 = MultiMachineYoloDetector(
        rtsp_url=RTSP_URL_2,
        model=shared_model,
        window_name="Camera 2 (Channel 24)",
        polygon_config_file="polygon_config_cam2.json"
    )

    # Set initial active focus to Camera 1 and synchronize continuous machine drawing tags
    MultiMachineYoloDetector.active_instance = cam1
    for cam in MultiMachineYoloDetector.all_instances:
        cam.active_drawing_name = cam._get_next_machine_name()

    # Start RTSP Stream Readers
    cam1.reader = RtspStreamReader(cam1.rtsp_url, frame_timeout=4.0)
    cam1.reader.start()

    cam2.reader = RtspStreamReader(cam2.rtsp_url, frame_timeout=4.0)
    cam2.reader.start()

    # Create Separate OpenCV Windows
    cv2.namedWindow(cam1.window_name, cv2.WINDOW_NORMAL)
    cv2.setMouseCallback(cam1.window_name, cam1._mouse_callback)

    cv2.namedWindow(cam2.window_name, cv2.WINDOW_NORMAL)
    cv2.setMouseCallback(cam2.window_name, cam2._mouse_callback)

    placeholder_frame = np.zeros((600, 800, 3), dtype=np.uint8)
    cv2.putText(placeholder_frame, "CONNECTING STREAM...", (240, 300), 
                cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 255), 2)

    try:
        while True:
            # Process & Render Camera 1
            frame1 = cam1.reader.read()
            if frame1 is not None:
                cam1.process_and_show_frame(frame1)
            else:
                ph1 = placeholder_frame.copy()
                cv2.putText(ph1, f"Cam 1 Retrying... ({cam1.reader.reconnect_attempt})", (20, 570), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (150, 150, 150), 1)
                cv2.imshow(cam1.window_name, ph1)

            # Process & Render Camera 2
            frame2 = cam2.reader.read()
            if frame2 is not None:
                cam2.process_and_show_frame(frame2)
            else:
                ph2 = placeholder_frame.copy()
                cv2.putText(ph2, f"Cam 2 Retrying... ({cam2.reader.reconnect_attempt})", (20, 570), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (150, 150, 150), 1)
                cv2.imshow(cam2.window_name, ph2)

            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                break
            elif key != 255:
                if MultiMachineYoloDetector.active_instance:
                    MultiMachineYoloDetector.active_instance.handle_key(key)
                else:
                    cam1.handle_key(key)

    except KeyboardInterrupt:
        print("\nStopping multi-camera tracker...")
    finally:
        cam1.reader.stop()
        cam2.reader.stop()
        cv2.destroyAllWindows()
        print("Clean exit.")

if __name__ == "__main__":
    main()
