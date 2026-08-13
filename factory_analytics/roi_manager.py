"""
Handles selecting, saving, and loading Regions of Interest (ROIs) per video.
Each video file gets its own list of ROIs, stored by filename in roi_config.json.
"""

import cv2
import json
import os


class ROIManager:
    def __init__(self, config_path):
        self.config_path = config_path
        self.all_config = self._load()

    def _load(self):
        if os.path.exists(self.config_path):
            with open(self.config_path, "r") as f:
                return json.load(f)
        return {}

    def _save(self):
        with open(self.config_path, "w") as f:
            json.dump(self.all_config, f, indent=2)

    def get_rois(self, video_path, first_frame):
        """Return saved ROIs for this video, or prompt the user to draw new ones."""
        key = os.path.basename(video_path)

        if key in self.all_config:
            rois = self.all_config[key]
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

        self.all_config[key] = rois
        self._save()
        print(f"[{key}] Saved {len(rois)} ROI(s) for future runs.")
        return rois

    def redraw_rois(self, video_path, first_frame):
        """Force a redraw for a video, overwriting any saved ROIs."""
        key = os.path.basename(video_path)
        if key in self.all_config:
            del self.all_config[key]
            self._save()
        return self.get_rois(video_path, first_frame)