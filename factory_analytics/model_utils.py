"""
Model utilities and tracking engines:
1. PolygonMotionEvaluator: Direct polygon-masked frame differencing for MC-001 (mc-001_motion_status.py logic).
2. YoloMachineDisplacementTracker: YOLO object centroid tracking & meter displacement for MC-002..MC-006 (detection.py logic).
3. LabelSmoother & helper utilities.
"""

import cv2
import numpy as np
import math
from collections import deque, Counter


def crop_polygon(frame, points):
    """Mask everything outside the polygon (blacked out), then crop tight to bbox."""
    pts = np.array(points, dtype=np.int32)
    x, y, w, h = cv2.boundingRect(pts)
    if w <= 0 or h <= 0:
        return np.zeros((1, 1, 3), dtype=np.uint8)

    mask = np.zeros(frame.shape[:2], dtype=np.uint8)
    cv2.fillPoly(mask, [pts], 255)
    masked = cv2.bitwise_and(frame, frame, mask=mask)
    return masked[y:y+h, x:x+w]


def polygon_centroid(polygon_points):
    """Compute area-weighted centroid via moments."""
    contour = polygon_points.reshape((-1, 1, 2)).astype(np.int32)
    m = cv2.moments(contour)
    if m["m00"] == 0:
        mean_pt = polygon_points.mean(axis=0)
        return int(round(mean_pt[0])), int(round(mean_pt[1]))
    return int(round(m["m10"] / m["m00"])), int(round(m["m01"] / m["m00"]))


def get_label_color(final_label):
    if final_label == "running":
        return (0, 255, 0)
    elif final_label == "stopped":
        return (0, 0, 255)
    else:
        return (0, 165, 255)


class LabelSmoother:
    """Rolling majority-vote smoother to eliminate frame-to-frame label flicker."""
    def __init__(self, window_size=5):
        self.window_size = window_size
        self.history = {}

    def smooth(self, channel_key, machine_id, raw_label):
        key = (channel_key, machine_id)
        if key not in self.history:
            self.history[key] = deque(maxlen=self.window_size)
        self.history[key].append(raw_label)
        return Counter(self.history[key]).most_common(1)[0][0]


# ==============================================================================
# MC-001 Polygon Motion Evaluator (Frame Differencing Engine)
# ==============================================================================
class PolygonMotionEvaluator:
    """Frame-differencing motion detector restricted to ONE machine's polygon region."""
    def __init__(self, polygon_points, pixel_threshold=80, diff_threshold=25):
        self.polygon_points = np.array(polygon_points, dtype=np.int32)
        self.pixel_threshold = pixel_threshold
        self.diff_threshold = diff_threshold
        self._prev_gray_masked = None

        x, y, w, h = cv2.boundingRect(self.polygon_points.reshape((-1, 1, 2)))
        self.bbox = (x, y, x + w, y + h)

        shifted_points = (self.polygon_points - np.array([x, y])).reshape((-1, 1, 2))
        mask = np.zeros((max(1, h), max(1, w)), dtype=np.uint8)
        cv2.fillPoly(mask, [shifted_points], 255)
        self.mask = mask

    def evaluate(self, frame):
        x1, y1, x2, y2 = self.bbox
        h, w = frame.shape[:2]
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)

        crop = frame[y1:y2, x1:x2]
        if crop.size == 0 or crop.shape[:2] != self.mask.shape:
            return "stopped", 0, 50.0

        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (5, 5), 0)
        gray_masked = cv2.bitwise_and(gray, gray, mask=self.mask)

        if self._prev_gray_masked is None:
            self._prev_gray_masked = gray_masked
            return "stopped", 0, 50.0

        diff = cv2.absdiff(gray_masked, self._prev_gray_masked)
        self._prev_gray_masked = gray_masked

        _, motion_mask = cv2.threshold(diff, self.diff_threshold, 255, cv2.THRESH_BINARY)
        moving_pixel_count = cv2.countNonZero(motion_mask)

        state = "running" if moving_pixel_count >= self.pixel_threshold else "stopped"
        # Confidence score based on pixel ratio
        roi_area = cv2.countNonZero(self.mask)
        confidence = min(99.0, max(50.0, 50.0 + (moving_pixel_count / max(1, roi_area) * 200.0)))
        return state, moving_pixel_count, confidence


# ==============================================================================
# MC-002 .. MC-006 YOLO Object Detection & Displacement Tracker (detection.py logic)
# ==============================================================================
class YoloRoiDisplacementTracker:
    """
    Tracks detected objects inside polygon ROI and calculates centroid displacement (meters).
    Preserves 100% of detection.py tracking, 1m-sliding-window memory, and 8-direction vectors.
    """
    def __init__(self, polygon_points, pixels_per_meter=50.0, min_displacement_meters=1.0,
                 history_len=15, movement_window_len=300):
        self.polygon_points = np.array(polygon_points, dtype=np.int32)
        self.pixels_per_meter = pixels_per_meter
        self.min_displacement_meters = min_displacement_meters
        self.centroid_history = deque(maxlen=history_len)
        self.movement_history_1m = deque(maxlen=movement_window_len)
        self.last_displacement_meters = 0.0
        self.last_displacement_px = 0.0
        self.last_direction = "STATIONARY"
        self.curr_centroid = None
        self.prev_centroid = None

    def match_and_update(self, detection_boxes, confidences=None):
        """
        detection_boxes: list of (x1, y1, x2, y2)
        Matches boxes whose center falls inside the machine polygon.
        Calculates centroid spatial displacement (dx, dy) in meters inside the ROI.
        Machine is marked active ('running') ONLY if box displacement in recent 1m window >= min_displacement_meters.
        """
        matched_centroids = []
        matched_confs = []

        if confidences is None or len(confidences) != len(detection_boxes):
            confidences = [0.5] * len(detection_boxes)

        for box, conf in zip(detection_boxes, confidences):
            x1, y1, x2, y2 = box
            cx = (x1 + x2) / 2.0
            cy = (y1 + y2) / 2.0
            if cv2.pointPolygonTest(self.polygon_points, (cx, cy), False) >= 0:
                matched_centroids.append((cx, cy))
                matched_confs.append(conf)

        if matched_centroids:
            # Average centroid if multiple detections in ROI
            avg_cx = sum(c[0] for c in matched_centroids) / len(matched_centroids)
            avg_cy = sum(c[1] for c in matched_centroids) / len(matched_centroids)
            curr_pos = (avg_cx, avg_cy)
            avg_conf = (sum(matched_confs) / len(matched_confs)) * 100.0 if matched_confs else 50.0

            self.centroid_history.append(curr_pos)
            self.curr_centroid = curr_pos

            # Calculate displacement in meters against centroid from 4+ frames ago
            if len(self.centroid_history) >= 4:
                prev_pos = self.centroid_history[0]
                self.prev_centroid = prev_pos

                dx = curr_pos[0] - prev_pos[0]
                dy = curr_pos[1] - prev_pos[1]
                displacement_px = math.hypot(dx, dy)
                displacement_m = displacement_px / self.pixels_per_meter

                self.last_displacement_meters = round(displacement_m, 2)
                self.last_displacement_px = round(displacement_px, 1)
                self.last_direction = self._calculate_direction(dx, dy)
                self.movement_history_1m.append(displacement_m)
            else:
                self.movement_history_1m.append(0.0)
        else:
            self.movement_history_1m.append(0.0)
            self.last_displacement_meters = 0.0
            self.last_displacement_px = 0.0
            self.last_direction = "NO OBJECT"
            self.curr_centroid = None
            self.prev_centroid = None
            avg_conf = 50.0

        # LIVE STATUS UPDATE:
        # Machine is ACTIVE ('running') ONLY if recent displacement >= min_displacement_meters (1.0m)
        max_recent_displacement_m = max(self.movement_history_1m) if self.movement_history_1m else 0.0
        if max_recent_displacement_m >= self.min_displacement_meters:
            state = "running"
        else:
            state = "stopped"

        return state, self.last_displacement_meters, avg_conf

    @staticmethod
    def _calculate_direction(dx, dy):
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
