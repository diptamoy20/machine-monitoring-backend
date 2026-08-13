"""
Unattended batch auto-labeling for motion-based training data.

Instead of manually pausing and pressing keys while watching the whole
video, this walks through the video automatically, computes a motion
score for each machine's ROI at every sampled interval, and sorts each
sample straight into RUNNING/ or STOPPED/ based on a threshold you set
-- no interaction needed while it runs.

Samples with a score too close to the threshold (ambiguous) are SKIPPED
by default rather than guessed at -- this keeps your dataset clean
without you having to manually filter out borderline/wrong labels.

A CSV log of every decision (including skipped ones) is written so you
can review borderline cases afterward and hand-correct only the few
that matter, instead of watching the whole video.

Usage:
    python batch_auto_label.py --source "video.mp4" --out motion_data ^
        --machine m1 30 70 260 260 --threshold 4.0 ^
        --machine m2 680 150 900 320 --threshold-m2 3.0

    (per-machine threshold overrides are optional -- see --machine-threshold)
"""

import argparse
import csv
import os
import time

import cv2
import numpy as np


def frame_to_diff_image(prev_gray, curr_gray):
    prev_blur = cv2.GaussianBlur(prev_gray, (5, 5), 0)
    curr_blur = cv2.GaussianBlur(curr_gray, (5, 5), 0)
    diff = cv2.absdiff(prev_blur, curr_blur)
    diff = cv2.normalize(diff, None, 0, 255, cv2.NORM_MINMAX)
    return cv2.cvtColor(diff, cv2.COLOR_GRAY2BGR)


def main(source, out_dir, machines, default_threshold, margin, sample_seconds):
    for mid in machines:
        for label in ["RUNNING", "STOPPED"]:
            os.makedirs(os.path.join(out_dir, mid, label), exist_ok=True)

    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        print(f"Could not open source: {source}")
        return

    fps = cap.get(cv2.CAP_PROP_FPS)
    if not fps or fps <= 1:
        fps = 25
    sample_every_frames = max(1, int(fps * sample_seconds))

    prev_gray = {mid: None for mid in machines}
    counts = {mid: {"RUNNING": 0, "STOPPED": 0, "SKIPPED": 0} for mid in machines}

    log_path = os.path.join(out_dir, "auto_label_log.csv")
    log_rows = []

    frame_idx = 0
    print(f"Sampling every {sample_seconds}s (~{sample_every_frames} frames). Running unattended...")

    while True:
        ok, frame = cap.read()
        if not ok:
            break

        if frame_idx % sample_every_frames == 0:
            for mid, (x1, y1, x2, y2, threshold) in machines.items():
                crop = frame[y1:y2, x1:x2]
                if crop.size == 0:
                    continue
                gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
                gray = cv2.GaussianBlur(gray, (5, 5), 0)

                if prev_gray[mid] is not None and prev_gray[mid].shape == gray.shape:
                    diff = cv2.absdiff(prev_gray[mid], gray)
                    score = float(diff.mean())

                    lower_bound = threshold - margin
                    upper_bound = threshold + margin

                    t = frame_idx / fps
                    if score >= upper_bound:
                        label = "RUNNING"
                    elif score <= lower_bound:
                        label = "STOPPED"
                    else:
                        label = None  # ambiguous, skip saving but still log it

                    if label is not None:
                        diff_img = frame_to_diff_image(prev_gray[mid], gray)
                        filename = f"{mid}_{label}_{int(time.time()*1000)}_{frame_idx}.jpg"
                        path = os.path.join(out_dir, mid, label, filename)
                        cv2.imwrite(path, diff_img)
                        counts[mid][label] += 1
                    else:
                        counts[mid]["SKIPPED"] += 1
                        filename = ""

                    log_rows.append([mid, f"{t:.1f}", f"{score:.2f}", threshold, label or "SKIPPED", filename])

                prev_gray[mid] = gray

        frame_idx += 1

    cap.release()

    with open(log_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["machine_id", "time_seconds", "motion_score", "threshold_used", "label", "filename"])
        writer.writerows(log_rows)

    print("\nDone. Results:")
    for mid in machines:
        c = counts[mid]
        print(f"  {mid}: RUNNING={c['RUNNING']}  STOPPED={c['STOPPED']}  SKIPPED(ambiguous)={c['SKIPPED']}")
    print(f"\nFull decision log: {log_path}")
    print("Review borderline entries in the log if a class count looks off, "
          "or spot-check a handful of saved images per class before training.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, help="Video file path")
    parser.add_argument("--out", default="motion_data", help="Output folder")
    parser.add_argument("--interval", type=float, default=1.0, help="Sample every N seconds")
    parser.add_argument("--margin", type=float, default=1.0,
                         help="Scores within +/- this margin of the threshold are skipped as ambiguous")
    parser.add_argument("--machine", action="append", nargs=6,
                         metavar=("ID", "X1", "Y1", "X2", "Y2", "THRESHOLD"),
                         help="Define a machine: ROI box + its motion-score threshold. Repeat per machine.")
    args = parser.parse_args()

    if not args.machine:
        print("ERROR: define at least one --machine ID X1 Y1 X2 Y2 THRESHOLD")
    else:
        machines = {}
        for m in args.machine:
            mid, x1, y1, x2, y2, threshold = m
            machines[mid] = (int(x1), int(y1), int(x2), int(y2), float(threshold))

        main(args.source, args.out, machines, default_threshold=None, margin=args.margin, sample_seconds=args.interval)