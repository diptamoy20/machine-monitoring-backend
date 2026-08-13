"""
Handles ONE-TIME triggered clip recording per machine (per ROI).

Workflow:
1. Records a single 30-second clip into DETECTION_DIR (a temporary/staging
   folder) on the first confident running/stopped detection for this machine.
   OpenCV's VideoWriter uses 'mp4v' codec here, which is NOT browser-playable
   on its own - it's just used as an intermediate recording format.
2. Once recording finishes, the clip is transcoded to H.264 (browser-compatible)
   directly into FINAL_DIR (the folder FastAPI serves as static files,
   e.g. app/static/videos) using FFmpeg. The original mp4v file is deleted
   after a successful transcode.
3. Notifies the API via PATCH /api/machines/{machine_id} with the new
   status, video_url, and detected_at timestamp.
4. Only ONE clip is saved per machine per video-processing session.

REQUIRES: FFmpeg must be installed and accessible on PATH.
Check with: ffmpeg -version
"""

import cv2
import os
import shutil
import subprocess
import requests
from datetime import datetime


class ClipRecorder:
    def __init__(self, detection_dir, final_dir, record_seconds, api_base_url, machine_id):
        self.detection_dir = detection_dir
        self.final_dir = final_dir
        self.record_seconds = record_seconds
        self.api_base_url = api_base_url
        self.machine_id = machine_id

        os.makedirs(self.detection_dir, exist_ok=True)
        os.makedirs(self.final_dir, exist_ok=True)

        self.recording = False
        self.already_saved = False
        self.writer = None
        self.frames_written = 0
        self.frames_target = 0
        self.filename = None       # temp file path (mp4v, in detection_dir)
        self.final_path = None     # final file path (H.264, in final_dir)

    def _generate_filename(self, status):
        now = datetime.now()
        timestamp = now.strftime("%Y-%m-%d_%H-%M-%S")
        status_label = status.capitalize()
        base_name = f"{self.machine_id}_{status_label}_{timestamp}.mp4"
        return os.path.join(self.detection_dir, base_name), base_name

    def maybe_start(self, frame, fps, should_trigger, status):
        if self.already_saved or self.recording:
            return

        if should_trigger:
            self.filename, base_name = self._generate_filename(status)
            self.final_path = os.path.join(self.final_dir, base_name)

            h, w = frame.shape[:2]
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            self.writer = cv2.VideoWriter(self.filename, fourcc, fps, (w, h))
            self.frames_target = int(round(fps * self.record_seconds))
            self.recording = True
            self.frames_written = 0
            print(f"[RECORDING STARTED] {self.machine_id} status={status} -> {self.filename} "
                  f"({self.frames_target} frames)")

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
            print(f"[RECORDING FINISHED{tag}] {self.machine_id} -> {self.filename}")

            transcoded = self._transcode_to_h264(self.filename, self.final_path)

            if transcoded:
                print(f"[TRANSCODED] {self.machine_id} -> {self.final_path}")
                try:
                    os.remove(self.filename)  # clean up the original mp4v intermediate file
                except OSError as e:
                    print(f"[CLEANUP WARNING] Could not remove temp file: {e}")
                self.filename = self.final_path
            else:
                # Fallback: move the original file so it's not lost, even
                # though it likely won't play in-browser without transcoding
                print(f"[TRANSCODE FAILED] Falling back to plain move (may not play in browser)")
                try:
                    shutil.move(self.filename, self.final_path)
                    self.filename = self.final_path
                except Exception as e:
                    print(f"[MOVE FAILED] {self.machine_id} could not move clip: {e}")

            self._notify_api()
            self.already_saved = True

        self.recording = False
        self.writer = None

    def _transcode_to_h264(self, input_path, output_path):
        """Converts the OpenCV-written clip to browser-compatible H.264 using FFmpeg."""
        cmd = [
            "ffmpeg", "-y",
            "-i", input_path,
            "-c:v", "libx264",
            "-preset", "fast",
            "-pix_fmt", "yuv420p",       # ensures broad browser/device compatibility
            "-movflags", "+faststart",   # allows playback to start before full download
            output_path
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        except FileNotFoundError:
            print("[TRANSCODE ERROR] ffmpeg not found on PATH. "
                  "Install FFmpeg and ensure 'ffmpeg -version' works in your terminal.")
            return False
        except subprocess.TimeoutExpired:
            print("[TRANSCODE ERROR] ffmpeg timed out after 120s.")
            return False

        if result.returncode != 0:
            print(f"[TRANSCODE FAILED] ffmpeg error:\n{result.stderr}")
            return False
        return True

    def _notify_api(self):
        base_name = os.path.basename(self.filename)
        detected_at = datetime.now().astimezone().isoformat()   # includes timezone offset

        parts = os.path.splitext(base_name)[0].split("_")
        status_raw = parts[1] if len(parts) > 1 else "unknown"
        status = status_raw.lower()

        status_map = {"running": "running", "stopped": "stop"}
        api_status = status_map.get(status, status)

        payload = {
            "status": api_status,
            "video_url": f"/static/videos/{base_name}",
            "detected_at": detected_at,
            }

        url = f"{self.api_base_url}/api/machines/{self.machine_id}"
        try:
            response = requests.patch(url, json=payload, timeout=5)
            if response.status_code == 200:
                print(f"[API UPDATED] {self.machine_id} -> {payload}")
            else:
                print(f"[API UPDATE FAILED] {self.machine_id} {response.status_code}: {response.text}")
        except requests.exceptions.RequestException as e:
            print(f"[API UPDATE ERROR] {self.machine_id} could not reach API: {e}")