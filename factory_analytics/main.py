import cv2
import time
import numpy as np
from rtsp_reader import RtspStreamReader
import config

CAMERA_INDEX = 1


def on_connect():
    print(">>> STREAM RESTORED <<<")


def on_disconnect():
    print(">>> STREAM LOST - RECOVERING... <<<")


def main():
    rtsp_url = config.RTSP_URLS[CAMERA_INDEX]

    print(f"Testing camera index {CAMERA_INDEX}: {rtsp_url}")
    print("Initializing ULTIMATE RTSP Reader...")

    reader = RtspStreamReader(
        rtsp_url,
        frame_timeout=4.0,
        on_connect=on_connect,
        on_disconnect=on_disconnect
    )
    reader.start()

    window_name = "Ultimate RTSP"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)

    placeholder_frame = np.zeros((600, 800, 3), dtype=np.uint8)
    cv2.putText(placeholder_frame, "NO SIGNAL", (250, 300),
               cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 0, 255), 4)
    cv2.putText(placeholder_frame, "Connecting...", (320, 360),
               cv2.FONT_HERSHEY_SIMPLEX, 0.8, (200, 200, 200), 1)

    try:
        while True:
            frame = reader.read()

            if frame is not None:
                metrics = reader.get_metrics()
                h, w = frame.shape[:2]

                cv2.putText(frame, f"FPS: {metrics['fps']:.1f}", (20, 40),
                           cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

                tech_text = f"Proto: {metrics['strategy']} | Drops: {metrics['dropped']} | Retries: {metrics['reconnects']}"
                cv2.putText(frame, tech_text, (20, h - 20),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 200), 2)

                cv2.imshow(window_name, frame)
            else:
                current_placeholder = placeholder_frame.copy()
                cv2.putText(current_placeholder, f"Retrying... ({reader.reconnect_attempt})", (10, 580),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.5, (100, 100, 100), 1)

                cv2.imshow(window_name, current_placeholder)

                if cv2.waitKey(100) & 0xFF == ord('q'):
                    break
                continue

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
