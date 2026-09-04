"""
Check whether a list of RTSP streams are reachable and producing frames.

SETUP (once):
    pip install opencv-python

RUN:
    python check_rtsp.py

Edit the RTSP_URLS list below, or pass URLs as command-line arguments:
    python check_rtsp.py "rtsp://..." "rtsp://..."

For each stream, this will:
    - Attempt to open the connection (with a timeout)
    - Try to read one frame
    - Report OK / FAILED with a reason
    - Save a snapshot .jpg for any stream that succeeds, so you can visually confirm
"""

import sys
import time
from pathlib import Path

import cv2

RTSP_URLS = [
    "rtsp://admin:admin@123@103.57.247.234:554/cam/realmonitor?channel=23&subtype=1",
    "rtsp://admin:admin@123@103.57.247.234:554/cam/realmonitor?channel=22&subtype=1",
    "rtsp://admin:admin@123@103.57.247.234:554/cam/realmonitor?channel=24&subtype=1",
    "rtsp://admin:admin@123@103.57.247.234:554/cam/realmonitor?channel=25&subtype=1",
]

TIMEOUT_MS = 8000  # connection + read timeout per stream
OUT_DIR = Path("rtsp_snapshots")


def check_stream(url: str, index: int) -> dict:
    label = f"Stream {index}"
    print(f"[{label}] Connecting...", end=" ", flush=True)

    cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
    cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, TIMEOUT_MS)
    cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, TIMEOUT_MS)

    if not cap.isOpened():
        cap.release()
        print("FAILED (could not open stream)")
        return {"url": url, "ok": False, "reason": "could not open stream"}

    start = time.time()
    ret, frame = cap.read()
    elapsed = time.time() - start
    cap.release()

    if not ret or frame is None:
        print(f"FAILED (opened but no frame received, {elapsed:.1f}s)")
        return {"url": url, "ok": False, "reason": "no frame received"}

    h, w = frame.shape[:2]
    OUT_DIR.mkdir(exist_ok=True)
    snap_path = OUT_DIR / f"stream_{index}.jpg"
    cv2.imwrite(str(snap_path), frame)

    print(f"OK ({w}x{h}, {elapsed:.1f}s) -> saved {snap_path}")
    return {"url": url, "ok": True, "resolution": f"{w}x{h}", "snapshot": str(snap_path)}


def main():
    urls = sys.argv[1:] if len(sys.argv) > 1 else RTSP_URLS
    if not urls:
        print("No RTSP URLs provided.")
        sys.exit(1)

    results = []
    for i, url in enumerate(urls, start=1):
        results.append(check_stream(url, i))

    print("\n" + "=" * 50)
    ok_count = sum(1 for r in results if r["ok"])
    print(f"Summary: {ok_count}/{len(results)} streams reachable")
    for i, r in enumerate(results, start=1):
        status = "OK" if r["ok"] else f"FAILED ({r['reason']})"
        print(f"  Stream {i}: {status}")


if __name__ == "__main__":
    main()