"""
Handles ONE-TIME triggered clip recording per video processing session.
Records a single 30-second clip on the first confident running/stopped
detection (of any machine), then stops triggering entirely for the rest
of that video - avoids saving multiple/random clips.
"""

import cv2
import os
from datetime import datetime


class ClipRecorder:
    def __init__(self, detection_dir, record_seconds):
        self.detection_dir = detection_dir
        self.record_seconds = record_seconds
        os.makedirs(self.detection_dir, exist_ok=True)

        self.recording = False
        self.already_saved = False   # ensures only ONE clip per video session
        self.writer = None
        self.frames_written = 0
        self.frames_target = 0
        self.filename = None

    def _generate_filename(self, status):
        now = datetime.now()
        timestamp = now.strftime("%Y-%m-%d_%H-%M-%S")
        status_label = status.capitalize()   # "running" -> "Running", "stopped" -> "Stopped"
        return os.path.join(self.detection_dir, f"{status_label}_{timestamp}.mp4")

    def maybe_start(self, frame, fps, should_trigger, status):
        if self.already_saved or self.recording:
            return  # only one clip per session - no further triggers once saved/in-progress

        if should_trigger:
            self.filename = self._generate_filename(status)
            h, w = frame.shape[:2]
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            self.writer = cv2.VideoWriter(self.filename, fourcc, fps, (w, h))
            self.frames_target = int(round(fps * self.record_seconds))
            self.recording = True
            self.frames_written = 0
            print(f"[RECORDING STARTED] Status={status} -> {self.filename} ({self.frames_target} frames)")

    def write_if_recording(self, frame):
        if not self.recording:
            return
        self.writer.write(frame)
        self.frames_written += 1
        if self.frames_written >= self.frames_target:
            self.stop(early=False)

    def stop(self, early=True):
        if self.recording and self.writer is not None:
            self.writer.release()
            tag = " - video ended early" if early else ""
            print(f"[RECORDING FINISHED{tag}] Saved: {self.filename}")
            self.already_saved = True
        self.recording = False
        self.writer = None