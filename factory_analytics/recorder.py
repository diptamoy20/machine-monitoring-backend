"""
Handles ONE-TIME triggered clip recording per machine (per ROI).

Workflow:
1. Records a clip into DETECTION_DIR on the first confident running/stopped
   detection for this machine. Also saves a JPEG snapshot of the triggering
   frame at the same moment.
2. Recording is capped by WALL-CLOCK TIME (record_seconds), not frame count -
   this guarantees a clip always finishes in bounded real time even if the
   server can't sustain the target fps (e.g. slow CPU inference across
   multiple ROIs). The actual achieved fps is computed from frames_written /
   elapsed_time and passed to ffmpeg during transcoding, so the final video's
   playback speed reflects real time rather than looking sped up.
3. The video is transcoded to H.264 and moved into FINAL_DIR.
   The image is saved directly into FINAL_IMAGE_DIR (no transcoding needed).
4. Notifies the API in TWO ways, but ONLY if the final video file is
   confirmed to exist on disk:
   a) PATCH /api/machines/{machine_id}   - updates status, video_url, image_url
   b) POST  /api/detections              - logs a permanent history event
5. Only ONE clip+image is saved per machine per video-processing session.

If cam_ip/cam_channel are provided (live RTSP pipeline), both are
appended to the evidence filename for traceability back to the source
camera. File-based pipelines that don't pass them keep the original
filename format unchanged.

REQUIRES: FFmpeg must be installed and accessible on PATH.
Check with: ffmpeg -version
"""

import cv2
import os
import time
import shutil
import subprocess
import requests
from datetime import datetime


class ClipRecorder:
    def __init__(self, detection_dir, final_dir, final_image_dir, record_seconds, api_base_url, machine_id,
                 cam_ip=None, cam_channel=None):
        self.detection_dir = detection_dir
        self.final_dir = final_dir
        self.final_image_dir = final_image_dir
        self.record_seconds = record_seconds
        self.api_base_url = api_base_url
        self.machine_id = machine_id
        self.cam_ip = cam_ip
        self.cam_channel = cam_channel

        os.makedirs(self.detection_dir, exist_ok=True)
        os.makedirs(self.final_dir, exist_ok=True)
        os.makedirs(self.final_image_dir, exist_ok=True)

        self.recording = False
        self.already_saved = False
        self.writer = None
        self.frames_written = 0
        self.declared_fps = None
        self.start_time = None
        self.filename = None
        self.final_path = None
        self.image_path = None

    def _generate_filenames(self, status):
        now = datetime.now()
        timestamp = now.strftime("%Y-%m-%d_%H-%M-%S")
        status_label = status.capitalize()
        base_name = f"{self.machine_id}_{status_label}_{timestamp}"

        if self.cam_ip and self.cam_channel:
            base_name = f"{base_name}_{self.cam_ip}_{self.cam_channel}"

        video_temp_path = os.path.join(self.detection_dir, base_name + ".mp4")
        video_final_path = os.path.join(self.final_dir, base_name + ".mp4")
        image_final_path = os.path.join(self.final_image_dir, base_name + ".jpg")
        return video_temp_path, video_final_path, image_final_path, base_name

    def maybe_start(self, frame, fps, should_trigger, status):
        if self.already_saved or self.recording:
            return

        if should_trigger:
            self.filename, self.final_path, self.image_path, base_name = self._generate_filenames(status)

            try:
                cv2.imwrite(self.image_path, frame)
                print(f"[SNAPSHOT SAVED] {self.machine_id} -> {self.image_path}")
            except Exception as e:
                print(f"[SNAPSHOT FAILED] {self.machine_id} could not save image: {e}")
                self.image_path = None

            h, w = frame.shape[:2]
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            self.declared_fps = fps
            self.writer = cv2.VideoWriter(self.filename, fourcc, fps, (w, h))
            self.start_time = time.time()
            self.recording = True
            self.frames_written = 0
            print(f"[RECORDING STARTED] {self.machine_id} status={status} -> {self.filename} "
                  f"(target: {self.record_seconds}s wall-clock)")

    def write_if_recording(self, frame):
        if not self.recording:
            return
        self.writer.write(frame)
        self.frames_written += 1

        elapsed = time.time() - self.start_time
        if elapsed >= self.record_seconds:
            self.stop(early=False)

    def force_stop_if_recording(self):
        """Immediately finalize an in-progress recording, e.g. on stream disconnect,
        so it never spans across a reconnect gap."""
        if self.recording:
            print(f"[RECORDING FORCE-STOPPED] {self.machine_id} - stream disconnected mid-recording")
            self.stop(early=True)

    def stop(self, early=True):
        if self.recording and self.writer is not None:
            elapsed = time.time() - self.start_time if self.start_time else 0
            actual_fps = (self.frames_written / elapsed) if elapsed > 0 else self.declared_fps
            actual_fps = max(1.0, actual_fps)  # never pass 0/negative fps to ffmpeg

            self.writer.release()
            tag = " - video ended early" if early else ""
            print(f"[RECORDING FINISHED{tag}] {self.machine_id} -> {self.filename} "
                  f"({self.frames_written} frames in {elapsed:.1f}s, actual_fps={actual_fps:.2f})")

            transcoded = self._transcode_to_h264(self.filename, self.final_path, actual_fps)

            if transcoded:
                print(f"[TRANSCODED] {self.machine_id} -> {self.final_path}")
                try:
                    os.remove(self.filename)
                except OSError as e:
                    print(f"[CLEANUP WARNING] Could not remove temp file: {e}")
                self.filename = self.final_path
            else:
                print(f"[TRANSCODE FAILED] Falling back to plain move (may not play in browser)")
                try:
                    shutil.move(self.filename, self.final_path)
                    self.filename = self.final_path
                except Exception as e:
                    print(f"[MOVE FAILED] {self.machine_id} could not move clip: {e}")
                    self.filename = None

            if self.filename and os.path.exists(self.filename):
                self._notify_api()
            else:
                print(f"[API UPDATE SKIPPED] {self.machine_id} - no valid file to reference, "
                      f"database was NOT updated with a broken video_url")

            self.already_saved = True

        self.recording = False
        self.writer = None

    def _transcode_to_h264(self, input_path, output_path, input_fps=None):
        cmd = ["ffmpeg", "-y"]
        if input_fps:
            cmd += ["-r", str(round(input_fps, 2))]
        cmd += [
            "-i", input_path,
            "-c:v", "libx264",
            "-preset", "fast",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            output_path
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        except FileNotFoundError:
            print("[TRANSCODE ERROR] ffmpeg not found on PATH.")
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
        detected_at = datetime.now().astimezone().isoformat()

        parts = os.path.splitext(base_name)[0].split("_")
        status_raw = parts[1] if len(parts) > 1 else "unknown"
        status = status_raw.lower()

        status_map = {"running": "running", "stopped": "stop"}
        api_status = status_map.get(status, status)

        video_url = f"/static/videos/{base_name}"

        image_url = None
        if self.image_path and os.path.exists(self.image_path):
            image_base_name = os.path.basename(self.image_path)
            image_url = f"/static/images/{image_base_name}"

        patch_payload = {
            "status": api_status,
            "video_url": video_url,
            "detected_at": detected_at,
        }
        if image_url:
            patch_payload["image_url"] = image_url

        patch_url = f"{self.api_base_url}/api/machines/{self.machine_id}"
        try:
            response = requests.patch(patch_url, json=patch_payload, timeout=20)
            if response.status_code == 200:
                print(f"[API UPDATED] {self.machine_id} -> {patch_payload}")
            else:
                print(f"[API UPDATE FAILED] {self.machine_id} {response.status_code}: {response.text}")
        except requests.exceptions.RequestException as e:
            print(f"[API UPDATE ERROR] {self.machine_id} could not reach API: {e}")

        history_payload = {
            "mc_id": self.machine_id,
            "status": api_status,
            "video_url": video_url,
            "detected_at": detected_at,
        }
        history_url = f"{self.api_base_url}/api/detections"
        try:
            response = requests.post(history_url, json=history_payload, timeout=20)
            if response.status_code == 201:
                print(f"[HISTORY LOGGED] {self.machine_id} -> {history_payload}")
            else:
                print(f"[HISTORY LOG FAILED] {self.machine_id} {response.status_code}: {response.text}")
        except requests.exceptions.RequestException as e:
            print(f"[HISTORY LOG ERROR] {self.machine_id} could not reach API: {e}")
