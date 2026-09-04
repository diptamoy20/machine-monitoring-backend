"""
One-time polygon ROI selection tool for live RTSP camera streams.

Controls (while a frame is frozen):
    Left click   - add a polygon vertex
    Right click  - undo the last vertex
    c            - close the current polygon, assign it to a machine
    r            - reset the in-progress (unclosed) polygon
    n            - done with this camera, move to the next one
    q            - skip this camera entirely (no ROIs saved)

You can draw multiple polygons (multiple machines) per camera before
pressing "n". Already-configured cameras are skipped automatically -
delete that camera's entry in roi_config.json to redraw it.
"""

import re
import cv2
import numpy as np
import config
from roi_manager import ROIManager


def channel_key_from_url(url: str) -> str:
    match = re.search(r"channel=(\d+)", url)
    channel = match.group(1) if match else "unknown"
    return f"channel_{channel}"


class PolygonROISelector:
    def __init__(self, base_frame, valid_machine_ids):
        self.base_frame = base_frame
        self.valid_machine_ids = valid_machine_ids
        self.current_points = []
        self.completed = []  # list of {"shape": "polygon", "points": [...], "machine_id": ...}

    def mouse_callback(self, event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            self.current_points.append([x, y])
        elif event == cv2.EVENT_RBUTTONDOWN:
            if self.current_points:
                self.current_points.pop()

    def _prompt_for_machine_id(self, polygon_number):
        print(f"\nPolygon #{polygon_number}: which machine is this?")
        for i, mid in enumerate(self.valid_machine_ids, start=1):
            print(f"  {i}. {mid}")
        while True:
            choice = input(f"Enter number (1-{len(self.valid_machine_ids)}): ").strip()
            if choice.isdigit() and 1 <= int(choice) <= len(self.valid_machine_ids):
                return self.valid_machine_ids[int(choice) - 1]
            print("Invalid choice, try again.")

    def render(self):
        display = self.base_frame.copy()

        for poly in self.completed:
            pts = np.array(poly["points"], dtype=np.int32)
            cv2.polylines(display, [pts], isClosed=True, color=(0, 255, 0), thickness=2)
            label_pos = tuple(pts[0])
            cv2.putText(display, poly["machine_id"], label_pos,
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

        if len(self.current_points) > 0:
            pts = np.array(self.current_points, dtype=np.int32)
            for pt in self.current_points:
                cv2.circle(display, tuple(pt), 4, (0, 165, 255), -1)
            if len(self.current_points) > 1:
                cv2.polylines(display, [pts], isClosed=False, color=(0, 165, 255), thickness=2)

        cv2.putText(display, "Left click: add point | Right click: undo | c: close | n: next cam | q: skip",
                    (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

        return display

    def run(self, window_name):
        cv2.namedWindow(window_name)
        cv2.setMouseCallback(window_name, self.mouse_callback)

        while True:
            cv2.imshow(window_name, self.render())
            key = cv2.waitKey(20) & 0xFF

            if key == ord("c"):
                if len(self.current_points) < 3:
                    print("Need at least 3 points to close a polygon.")
                    continue
                machine_id = self._prompt_for_machine_id(len(self.completed) + 1)
                self.completed.append({
                    "shape": "polygon",
                    "points": self.current_points.copy(),
                    "machine_id": machine_id,
                })
                self.current_points = []
                print(f"Polygon saved for {machine_id}. Draw another, or press 'n' when done.")

            elif key == ord("r"):
                self.current_points = []
                print("Current polygon reset.")

            elif key == ord("n"):
                cv2.destroyWindow(window_name)
                return self.completed

            elif key == ord("q"):
                cv2.destroyWindow(window_name)
                return None


def select_roi_for_camera(url: str, roi_manager: ROIManager):
    key = channel_key_from_url(url)

    if key in roi_manager.all_config:
        print(f"[{key}] ROI already configured, skipping. "
              f"Delete its entry in {config.ROI_CONFIG_PATH} to redraw.")
        return

    print(f"[{key}] Connecting to stream...")
    cap = cv2.VideoCapture(url)
    if not cap.isOpened():
        print(f"[{key}] Failed to open stream. Skipping.")
        return

    print(f"[{key}] Live preview started. Press \"s\" to freeze a frame and start drawing.")
    window_name = f"Live Preview - {key}"
    frozen_frame = None

    while True:
        ret, frame = cap.read()
        if not ret:
            print(f"[{key}] Failed to read frame. Retrying...")
            continue

        cv2.imshow(window_name, frame)
        key_pressed = cv2.waitKey(1) & 0xFF

        if key_pressed == ord("s"):
            frozen_frame = frame.copy()
            break
        elif key_pressed == ord("q"):
            print(f"[{key}] Skipped by user.")
            cap.release()
            cv2.destroyWindow(window_name)
            return

    cap.release()
    cv2.destroyWindow(window_name)

    selector = PolygonROISelector(frozen_frame, config.MACHINE_IDS)
    result = selector.run(window_name)

    if result:
        roi_manager.save_rois_for_key(key, result)
        print(f"[{key}] Saved {len(result)} polygon ROI(s): {[r['machine_id'] for r in result]}")
    else:
        print(f"[{key}] No ROIs saved.")


def main():
    roi_manager = ROIManager(config.ROI_CONFIG_PATH, valid_machine_ids=config.MACHINE_IDS)

    for url in config.RTSP_URLS:
        select_roi_for_camera(url, roi_manager)

    print("ROI selection complete for all configured cameras.")


if __name__ == "__main__":
    main()

def cam_ip_from_url(url: str) -> str:
    match = re.search(r"@(\d{1,3}(?:\.\d{1,3}){3}):(\d+)", url)
    return match.group(1) if match else "unknown-ip"
