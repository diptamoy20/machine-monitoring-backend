"""
Assigns a persistent machine ID to each ROI using ByteTrack (via the
`supervision` library). Each drawn ROI is treated as a per-frame detection
of class "machine". Since ROIs are static, IDs will settle and stay stable
frame-to-frame - but this same code will work unchanged if you later swap
in a real object detector whose boxes move/appear dynamically.
"""

import numpy as np
import supervision as sv


class MachineTracker:
    def __init__(self):
        self.tracker = sv.ByteTrack()

    def update(self, rois):
        """
        rois: list of [x, y, w, h] in pixel coordinates
        Returns: dict {roi_index: machine_id}
        """
        if not rois:
            return {}

        xyxy = np.array([[x, y, x + w, y + h] for (x, y, w, h) in rois], dtype=np.float32)
        confidence = np.ones(len(rois), dtype=np.float32)
        class_id = np.zeros(len(rois), dtype=int)

        detections = sv.Detections(xyxy=xyxy, confidence=confidence, class_id=class_id)
        tracked = self.tracker.update_with_detections(detections)

        result = {}
        for i, box in enumerate(tracked.xyxy):
            roi_index = self._match_roi_index(box, rois)
            if roi_index is not None:
                result[roi_index] = int(tracked.tracker_id[i])
        return result

    @staticmethod
    def _match_roi_index(box, rois):
        bx1, by1 = box[0], box[1]
        for idx, (x, y, w, h) in enumerate(rois):
            if abs(x - bx1) < 5 and abs(y - by1) < 5:
                return idx
        return None