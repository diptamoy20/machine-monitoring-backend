"""
Capture labeled motion-difference training images.

Works with a webcam, an RTSP stream, OR a recorded video file (real
client footage) -- just change --source. For recorded files, use
SPACE to pause and 'n' to step one frame at a time so you can land
precisely on clear RUNNING/STOPPED moments instead of the video
racing past too fast to label accurately.

Each saved image is the DIFFERENCE between two consecutive frames of
the ROI, converted to a 3-channel image (so it's compatible with
standard pretrained CNN input), not the raw color frame.

Controls:
    r      -> save current motion-diff as RUNNING
    s      -> save current motion-diff as STOPPED
    SPACE  -> pause / resume playback
    n      -> step one frame forward (only while paused)
    wasd = move ROI box, +/- = resize
    q      -> quit

Usage:
    python capture_motion_data.py --source 0 --out motion_data
    python capture_motion_data.py --source "camera_1.mp4" --out motion_data
    python capture_motion_data.py --source "rtsp://..." --out motion_data
"""

import argparse
import os
import time

import cv2
import numpy as np

KEY_TO_LABEL = {ord("r"): "RUNNING", ord("s"): "STOPPED"}


def frame_to_diff_image(prev_gray, curr_gray):
    """Compute the motion-difference image and convert to 3-channel
    (replicated grayscale) so it works directly with pretrained CNNs
    that expect 3-channel RGB input. Blurs first to suppress
    compression-noise speckle that would otherwise dominate the diff
    on real, compressed camera footage."""
    prev_blur = cv2.GaussianBlur(prev_gray, (5, 5), 0)
    curr_blur = cv2.GaussianBlur(curr_gray, (5, 5), 0)
    diff = cv2.absdiff(prev_blur, curr_blur)
    diff = cv2.normalize(diff, None, 0, 255, cv2.NORM_MINMAX)
    diff_3ch = cv2.cvtColor(diff, cv2.COLOR_GRAY2BGR)
    return diff_3ch


def main(source, out_dir):
    for label in KEY_TO_LABEL.values():
        os.makedirs(os.path.join(out_dir, label), exist_ok=True)

    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        print(f"Could not open source: {source}")
        return

    source_fps = cap.get(cv2.CAP_PROP_FPS)
    if not source_fps or source_fps <= 1:
        source_fps = 25  # sane fallback if the file doesn't report FPS
    frame_delay_ms = max(1, int(1000 / source_fps))

    box_w, box_h = 200, 150
    cx, cy = None, None
    move_step = 15
    prev_gray = None
    curr_gray = None
    saved_counts = {label: len(os.listdir(os.path.join(out_dir, label))) for label in KEY_TO_LABEL.values()}

    print("Controls: r=save RUNNING, s=save STOPPED, SPACE=pause/resume, n=step (while paused), "
          "wasd=move, +/-=resize, q=quit")
    print("Starting PAUSED -- press SPACE to begin playback, or 'n' to step frame-by-frame from the start.")
    print(f"Starting counts: {saved_counts}")

    # Always load the very first frame up front, regardless of paused state --
    # otherwise starting paused leaves 'frame' as None and crashes on frame.shape.
    ok, frame = cap.read()
    if not ok:
        print("Could not read the first frame from this source.")
        cap.release()
        return

    h0, w0 = frame.shape[:2]
    cx, cy = w0 // 2, h0 // 2
    x1_init, y1_init = max(0, cx - box_w // 2), max(0, cy - box_h // 2)
    x2_init, y2_init = min(w0, cx + box_w // 2), min(h0, cy + box_h // 2)
    first_crop = frame[y1_init:y2_init, x1_init:x2_init]
    curr_gray = cv2.cvtColor(first_crop, cv2.COLOR_BGR2GRAY) if first_crop.size > 0 else None

    paused = True  # start paused -- gives you control from frame 1 instead of racing through

    while True:
        need_new_frame = not paused
        if need_new_frame:
            ok, new_frame = cap.read()
            if not ok:
                print("Source read failed (end of video or stream lost).")
                break
            frame = new_frame

        h, w = frame.shape[:2]
        if cx is None:
            cx, cy = w // 2, h // 2

        x1, y1 = max(0, cx - box_w // 2), max(0, cy - box_h // 2)
        x2, y2 = min(w, cx + box_w // 2), min(h, cy + box_h // 2)
        crop = frame[y1:y2, x1:x2]

        if need_new_frame:
            prev_gray = curr_gray
            curr_gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.size > 0 else None

        display = frame.copy()
        box_color = (0, 165, 255) if paused else (255, 255, 255)
        cv2.rectangle(display, (x1, y1), (x2, y2), box_color, 2)
        status_text = "PAUSED (n=step)" if paused else "PLAYING"
        cv2.putText(display, f"[{status_text}]  r=RUNNING  s=STOPPED  SPACE=pause  wasd=move  q=quit",
                    (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.5, box_color, 1)
        counts_text = "  ".join(f"{k}:{v}" for k, v in saved_counts.items())
        cv2.putText(display, counts_text, (10, h - 15), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

        if prev_gray is not None and curr_gray is not None and prev_gray.shape == curr_gray.shape:
            diff_preview = frame_to_diff_image(prev_gray, curr_gray)
            preview_small = cv2.resize(diff_preview, (160, 120))
            display[10:130, w - 170:w - 10] = preview_small
            cv2.putText(display, "motion diff", (w - 170, 145), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 255), 1)

        cv2.imshow("Motion data capture", display)
        wait_ms = frame_delay_ms if not paused else 30
        key = cv2.waitKey(wait_ms) & 0xFF

        if key == ord("q"):
            break
        elif key == ord(" "):
            paused = not paused
        elif key == ord("n") and paused:
            ok, new_frame = cap.read()
            if ok:
                frame = new_frame
                prev_gray = curr_gray
                new_crop = frame[y1:y2, x1:x2]
                curr_gray = cv2.cvtColor(new_crop, cv2.COLOR_BGR2GRAY) if new_crop.size > 0 else None
            else:
                print("End of video reached.")
        elif key in (ord("+"), ord("=")):
            box_w += 10; box_h += 10
        elif key == ord("-"):
            box_w = max(20, box_w - 10); box_h = max(20, box_h - 10)
        elif key == ord("w"):
            cy -= move_step
        elif key == ord("a"):
            cx -= move_step
        elif key == ord("d"):
            cx += move_step
        elif key in KEY_TO_LABEL:
            if prev_gray is not None and curr_gray is not None and prev_gray.shape == curr_gray.shape:
                label = KEY_TO_LABEL[key]
                diff_img = frame_to_diff_image(prev_gray, curr_gray)
                filename = f"{label}_{int(time.time()*1000)}.jpg"
                path = os.path.join(out_dir, label, filename)
                cv2.imwrite(path, diff_img)
                saved_counts[label] += 1
                print(f"Saved {path}  (total {label}: {saved_counts[label]})")

    cap.release()
    cv2.destroyAllWindows()
    print("\nFinal counts:", saved_counts)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default="0", help="Camera index (e.g. 0), video file path, or RTSP URL")
    parser.add_argument("--out", default="motion_data", help="Output folder")
    args = parser.parse_args()

    source = int(args.source) if args.source.isdigit() else args.source
    main(source, args.out)