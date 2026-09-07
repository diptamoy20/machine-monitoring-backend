# """
# Check whether a list of RTSP streams are reachable and producing frames.

# SETUP (once):
#     pip install opencv-python

# RUN:
#     python check_rtsp.py

# Edit the RTSP_URLS list below, or pass URLs as command-line arguments:
#     python check_rtsp.py "rtsp://..." "rtsp://..."

# For each stream, this will:
#     - Attempt to open the connection (with a timeout)
#     - Try to read one frame
#     - Report OK / FAILED with a reason
#     - Save a snapshot .jpg for any stream that succeeds, so you can visually confirm
# """

# import sys
# import time
# from pathlib import Path

# import cv2

# RTSP_URLS = [
#     "rtsp://admin:admin@123@103.57.247.234:554/cam/realmonitor?channel=23&subtype=1",
#     "rtsp://admin:admin@123@103.57.247.234:554/cam/realmonitor?channel=22&subtype=1",
#     "rtsp://admin:admin@123@103.57.247.234:554/cam/realmonitor?channel=24&subtype=1",
#     "rtsp://admin:admin@123@103.57.247.234:554/cam/realmonitor?channel=25&subtype=1",
# ]

# TIMEOUT_MS = 8000  # connection + read timeout per stream
# OUT_DIR = Path("rtsp_snapshots")


# def check_stream(url: str, index: int) -> dict:
#     label = f"Stream {index}"
#     print(f"[{label}] Connecting...", end=" ", flush=True)

#     cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
#     cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, TIMEOUT_MS)
#     cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, TIMEOUT_MS)

#     if not cap.isOpened():
#         cap.release()
#         print("FAILED (could not open stream)")
#         return {"url": url, "ok": False, "reason": "could not open stream"}

#     start = time.time()
#     ret, frame = cap.read()
#     elapsed = time.time() - start
#     cap.release()

#     if not ret or frame is None:
#         print(f"FAILED (opened but no frame received, {elapsed:.1f}s)")
#         return {"url": url, "ok": False, "reason": "no frame received"}

#     h, w = frame.shape[:2]
#     OUT_DIR.mkdir(exist_ok=True)
#     snap_path = OUT_DIR / f"stream_{index}.jpg"
#     cv2.imwrite(str(snap_path), frame)

#     print(f"OK ({w}x{h}, {elapsed:.1f}s) -> saved {snap_path}")
#     return {"url": url, "ok": True, "resolution": f"{w}x{h}", "snapshot": str(snap_path)}


# def main():
#     urls = sys.argv[1:] if len(sys.argv) > 1 else RTSP_URLS
#     if not urls:
#         print("No RTSP URLs provided.")
#         sys.exit(1)

#     results = []
#     for i, url in enumerate(urls, start=1):
#         results.append(check_stream(url, i))

#     print("\n" + "=" * 50)
#     ok_count = sum(1 for r in results if r["ok"])
#     print(f"Summary: {ok_count}/{len(results)} streams reachable")
#     for i, r in enumerate(results, start=1):
#         status = "OK" if r["ok"] else f"FAILED ({r['reason']})"
#         print(f"  Stream {i}: {status}")


# if __name__ == "__main__":
#     main()

import cv2
import time
import numpy as np
from rtsp_reader import RtspStreamReader

def on_connect():
    print(">>> STREAM RESTORED <<<")

def on_disconnect():
    print(">>> STREAM LOST - RECOVERING... <<<")

def main():
    # rtsp_url = "rtsp://admin:Admin123%40@182.78.9.245:554/cam/realmonitor?channel=10&subtype=0"
    rtsp_url = "rtsp://admin:admin@123@103.57.247.234:554/cam/realmonitor?channel=23&subtype=1"
    
    
    print("Initializing ULTIMATE RTSP Reader...")
    print("Features: Smart Backoff, Adaptive Flow, Protocol Auto-Switching")
    
    reader = RtspStreamReader(
        rtsp_url, 
        frame_timeout=4.0, 
        on_connect=on_connect,
        on_disconnect=on_disconnect
    )
    reader.start()

    # Display Caching
    window_name = "Ultimate RTSP"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    
    # Pre-create "No Signal" slide to avoid re-generating it every loop
    placeholder_frame = np.zeros((600, 800, 3), dtype=np.uint8)
    cv2.putText(placeholder_frame, "NO SIGNAL", (250, 300), 
               cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 0, 255), 4)
    cv2.putText(placeholder_frame, "Connecting...", (320, 360), 
               cv2.FONT_HERSHEY_SIMPLEX, 0.8, (200, 200, 200), 1)

    try:
        while True:
            frame = reader.read()
            
            if frame is not None:
                # Get current stats
                metrics = reader.get_metrics()
                
                # Visuals
                # Just draw HUD on the frame directly
                h, w = frame.shape[:2]
                
                # Top Left: FPS & Status
                status_color = (0, 255, 0) # Green
                cv2.putText(frame, f"FPS: {metrics['fps']:.1f}", (20, 40), 
                           cv2.FONT_HERSHEY_SIMPLEX, 1, status_color, 2)
                
                # Bottom Left: Tech Stats
                tech_text = f"Proto: {metrics['strategy']} | Drops: {metrics['dropped']} | Retries: {metrics['reconnects']}"
                cv2.putText(frame, tech_text, (20, h - 20), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 200), 2)
                
                cv2.imshow(window_name, frame)
            else:
                # Show No Signal screen
                # Update retry count on placeholder if desired
                current_placeholder = placeholder_frame.copy()
                cv2.putText(current_placeholder, f"Retrying... ({reader.reconnect_attempt})", (10, 580), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.5, (100, 100, 100), 1)
                
                cv2.imshow(window_name, current_placeholder)
                
                # Slower wait key to save CPU when disconnected
                if cv2.waitKey(100) & 0xFF == ord('q'):
                    break
                continue # Skip the normal waitKey check below since we did it here

            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        reader.stop()
        cv2.destroyAllWindows()
        print("Clean exit.")

if __name__ == "__main__":
    main()
