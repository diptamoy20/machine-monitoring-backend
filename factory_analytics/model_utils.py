"""
Model input preparation and prediction stabilization utilities:
- letterbox_crop: preserves aspect ratio before feeding crops to the classifier
- LabelSmoother: majority-vote smoothing over recent frames per ROI
- resolve_final_label: applies a confidence floor, labeling low-confidence
  predictions as "uncertain" instead of trusting a noisy guess
"""

import cv2
import numpy as np
from collections import deque, Counter


def letterbox_crop(img, size):
    """Pad an image to a square canvas (preserving aspect ratio) before resizing."""
    h, w = img.shape[:2]
    scale = size / max(h, w)
    new_w, new_h = max(1, int(w * scale)), max(1, int(h * scale))
    resized = cv2.resize(img, (new_w, new_h))

    canvas = np.zeros((size, size, 3), dtype=np.uint8)
    top = (size - new_h) // 2
    left = (size - new_w) // 2
    canvas[top:top+new_h, left:left+new_w] = resized
    return canvas


class LabelSmoother:
    """Keeps a rolling history of raw predictions per (video, ROI) and returns
    the majority label over the last N frames, reducing frame-to-frame flicker."""

    def __init__(self, window_size):
        self.window_size = window_size
        self.history = {}

    def smooth(self, video_key, roi_idx, raw_label):
        key = (video_key, roi_idx)
        if key not in self.history:
            self.history[key] = deque(maxlen=self.window_size)
        self.history[key].append(raw_label)
        return Counter(self.history[key]).most_common(1)[0][0]


def resolve_final_label(smoothed_label, confidence, confidence_floor):
    """Below the confidence floor, display 'uncertain' instead of trusting the label."""
    if confidence < confidence_floor:
        return "uncertain"
    return smoothed_label


def get_label_color(final_label):
    """Consistent color mapping used across the app for drawing overlays."""
    if final_label == "running":
        return (0, 255, 0)
    elif final_label == "stopped":
        return (0, 0, 255)
    else:  # uncertain
        return (0, 165, 255)