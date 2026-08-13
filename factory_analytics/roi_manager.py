"""
Handles selecting, saving, and loading Regions of Interest (ROIs) per video.

Each ROI is stored as: {"bbox": [x, y, w, h], "machine_id": "MC-XXX"}

Machine IDs are generated automatically the moment a new ROI is drawn, using
a persistent counter stored in roi_config.json under the "_counter" key.
This counter never resets, so IDs stay unique across every video and every
script run - drawing a new ROI anywhere always gets a fresh, unused ID.
"""

import cv2
import json
import os


class ROIManager:
    def __init__(self, config_path, id_start=0):
        """
        id_start: set this to the highest machine number ALREADY used
        elsewhere (e.g. in your database) so new auto-generated IDs never
        collide with existing ones. E.g. if MC-001..MC-006 already exist
        in the DB, pass id_start=6 so new IDs begin at MC-007.
        """
        self.config_path = config_path
        self.all_config = self._load()

        if "_counter" not in self.all_config:
            self.all_config["_counter"] = id_start
            self._save()
        else:
            # Never let the counter regress below id_start, in case this
            # manager is reused with a higher starting point later.
            if self.all_config["_counter"] < id_start:
                self.all_config["_counter"] = id_start
                self._save()

    def _load(self):
        if os.path.exists(self.config_path):
            with open(self.config_path, "r") as f:
                data = json.load(f)
            return self._migrate_if_needed(data)
        return {}

    def _migrate_if_needed(self, data):
        """Upgrades old-format ROIs (plain [x,y,w,h] lists) into the new
        dict format with machine_id, without losing existing coordinates."""
        changed = False
        counter = data.get("_counter", 0)

        for key, rois in list(data.items()):
            if key == "_counter":
                continue
            new_rois = []
            for roi in rois:
                if isinstance(roi, dict) and "machine_id" in roi:
                    new_rois.append(roi)
                else:
                    counter += 1
                    new_rois.append({"bbox": list(roi), "machine_id": f"MC-{counter:03d}"})
                    changed = True
            data[key] = new_rois

        if changed:
            data["_counter"] = counter
            with open(self.config_path, "w") as f:
                json.dump(data, f, indent=2)
            print(f"[MIGRATED] Upgraded old ROI format, assigned machine IDs up to MC-{counter:03d}")

        return data

    def _save(self):
        with open(self.config_path, "w") as f:
            json.dump(self.all_config, f, indent=2)

    def _next_machine_id(self):
        counter = self.all_config.get("_counter", 0) + 1
        self.all_config["_counter"] = counter
        return f"MC-{counter:03d}"

    def get_rois(self, video_path, first_frame):
        """Returns list of {"bbox": [x,y,w,h], "machine_id": "MC-XXX"} for this video.
        Draws and assigns new IDs only if this video has no saved ROIs yet."""
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
        for box in boxes:
            if box[2] > 0 and box[3] > 0:
                machine_id = self._next_machine_id()
                rois.append({"bbox": list(map(int, box)), "machine_id": machine_id})

        if not rois:
            print(f"[{key}] No ROI selected — skipping this video.")
            return []

        self.all_config[key] = rois
        self._save()
        print(f"[{key}] Saved {len(rois)} ROI(s) with new IDs: "
              f"{[r['machine_id'] for r in rois]}")
        return rois

    def add_roi(self, video_path, first_frame):
        """Adds ONE new ROI to a video that already has saved ROIs,
        auto-generating a new machine_id for just that one box."""
        key = os.path.basename(video_path)
        existing = self.all_config.get(key, [])

        print(f"[{key}] Draw ONE new machine box. Press ENTER to confirm.")
        box = cv2.selectROI("Add New Machine ROI", first_frame, showCrosshair=True)
        cv2.destroyWindow("Add New Machine ROI")

        if box[2] == 0 or box[3] == 0:
            print(f"[{key}] No box drawn — nothing added.")
            return existing

        machine_id = self._next_machine_id()
        existing.append({"bbox": list(map(int, box)), "machine_id": machine_id})
        self.all_config[key] = existing
        self._save()
        print(f"[{key}] Added new ROI with ID: {machine_id}")
        return existing

    def redraw_rois(self, video_path, first_frame):
        """Forces a full redraw for a video, discarding old ROIs and IDs
        for that video and generating fresh ones."""
        key = os.path.basename(video_path)
        if key in self.all_config:
            del self.all_config[key]
            self._save()
        return self.get_rois(video_path, first_frame)