"""
Handles selecting, saving, and loading Regions of Interest (ROIs) per video.

Each ROI is stored as: {"bbox": [x, y, w, h], "machine_id": "MC-XXX"}

Machine IDs are NOT auto-generated - you have a fixed set of real machines
(MC-001 through MC-006). When drawing a new ROI, you will be prompted to pick
which real machine that box corresponds to. The same machine_id can be
reused across multiple videos.
"""

import cv2
import json
import os


class ROIManager:
    def __init__(self, config_path, valid_machine_ids):
        self.config_path = config_path
        self.valid_machine_ids = valid_machine_ids
        self.all_config = self._load()

    def _load(self):
        if os.path.exists(self.config_path):
            with open(self.config_path, "r") as f:
                data = json.load(f)
            return self._migrate_if_needed(data)
        return {}

    def _migrate_if_needed(self, data):
        if "_counter" in data:
            del data["_counter"]
            with open(self.config_path, "w") as f:
                json.dump(data, f, indent=2)
            print("[MIGRATED] Removed legacy auto-increment counter.")
        return data

    def _save(self):
        with open(self.config_path, "w") as f:
            json.dump(self.all_config, f, indent=2)

    def _prompt_for_machine_id(self, box_number):
        print(f"\nBox #{box_number}: which machine is this?")
        for i, mid in enumerate(self.valid_machine_ids, start=1):
            print(f"  {i}. {mid}")
        while True:
            choice = input(f"Enter number (1-{len(self.valid_machine_ids)}): ").strip()
            if choice.isdigit() and 1 <= int(choice) <= len(self.valid_machine_ids):
                return self.valid_machine_ids[int(choice) - 1]
            print("Invalid choice, try again.")

    def get_rois(self, video_path, first_frame):
        key = os.path.basename(video_path)

        if key in self.all_config:
            rois = self.all_config[key]
            print(f"[{key}] Loaded {len(rois)} saved ROI(s): "
                  f"{[r['machine_id'] for r in rois]}")
            return rois

        print(f"[{key}] No saved ROI found.")
        print("Draw a box around each machine. Press ENTER after each box.")
        print("When done drawing all boxes, press ENTER/ESC on an empty selection.")
        boxes = cv2.selectROIs("Select Machine ROI(s)", first_frame, showCrosshair=True)
        cv2.destroyWindow("Select Machine ROI(s)")

        rois = []
        box_number = 0
        for box in boxes:
            if box[2] > 0 and box[3] > 0:
                box_number += 1
                machine_id = self._prompt_for_machine_id(box_number)
                rois.append({"bbox": list(map(int, box)), "machine_id": machine_id})

        if not rois:
            print(f"[{key}] No ROI selected — skipping this video.")
            return []

        self.all_config[key] = rois
        self._save()
        print(f"[{key}] Saved {len(rois)} ROI(s): "
              f"{[r['machine_id'] for r in rois]}")
        return rois

    def redraw_rois(self, video_path, first_frame):
        key = os.path.basename(video_path)
        if key in self.all_config:
            del self.all_config[key]
            self._save()
        return self.get_rois(video_path, first_frame)
