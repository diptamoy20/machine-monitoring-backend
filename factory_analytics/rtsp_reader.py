import cv2
import threading
import time
import logging
import os
from collections import deque

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class RtspStreamReader:
    def __init__(self, rtsp_url, 
                 frame_timeout=5.0, 
                 on_connect=None, 
                 on_disconnect=None,
                 buffer_size=0, 
                 fflags="nobuffer", 
                 flags="low_delay",
                 use_gstreamer=True):
        self.rtsp_url = rtsp_url
        self.frame_timeout = frame_timeout
        self.on_connect = on_connect
        self.on_disconnect = on_disconnect
        self.buffer_size = buffer_size
        self.fflags = fflags
        self.flags = flags
        
        self.cap = None
        self.running = False
        self.thread = None
        self.connected = False
        
        self._frame_buffer = deque(maxlen=1)
        self._lock = threading.Lock()
        
        self.reconnect_attempt = 0
        self.strategies = [
            {"name": "FFMPEG TCP", "backend": "ffmpeg", "transport": "tcp", "failures": 0},
            {"name": "FFMPEG UDP", "backend": "ffmpeg", "transport": "udp", "failures": 0},
        ]
        
        if use_gstreamer:
            self.strategies.extend([
                {"name": "GSTREAMER TCP", "backend": "gstreamer", "transport": "tcp", "failures": 0},
                {"name": "GSTREAMER UDP", "backend": "gstreamer", "transport": "udp", "failures": 0},
            ])

        self.current_strategy_index = 0
        
        self.last_frame_time = 0
        self.fps = 0.0
        self.dropped_frames = 0
        self.read_frames = 0
        self._fps_counter = 0
        self._fps_start_time = 0

    def start(self):
        if self.running: return
        self.running = True
        self.thread = threading.Thread(target=self._update, daemon=True)
        self.thread.start()
        logger.info(f"Started ULTIMATE RTSP stream reader used for {self.rtsp_url}")

    def stop(self):
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join()
        self._release_resources()
        logger.info("Stopped RTSP stream reader.")

    def _update(self):
        self.last_frame_time = time.time()
        self._fps_start_time = time.time()

        while self.running:
            try:
                if self.cap is None or not self.cap.isOpened():
                    if not self._connect_smartly():
                        delay = self._get_backoff_delay()
                        logger.info(f"Connection failed. Retrying in {delay}s...")
                        time.sleep(delay)
                        continue
                    
                    self.reconnect_attempt = 0
                    self.last_frame_time = time.time()

                if self.connected and (time.time() - self.last_frame_time > self.frame_timeout):
                    logger.warning(f"Watchdog: Stream frozen for {time.time() - self.last_frame_time:.1f}s.")
                    self._handle_disconnect()
                    continue

                if self.cap and self.cap.isOpened():
                    ret = self.cap.grab()
                    
                    if ret:
                        self.last_frame_time = time.time()
                        self.read_frames += 1
                        
                        ret, frame = self.cap.retrieve()
                        
                        if ret:
                            with self._lock:
                                self._frame_buffer.append(frame)
                                if not self.connected:
                                    self.connected = True
                                    if self.on_connect: self.on_connect()
                            
                            self._update_metrics()
                        else:
                            self.dropped_frames += 1
                    else:
                        time.sleep(0.005)
                else:
                    time.sleep(0.1)

            except Exception as e:
                logger.error(f"Critical error in loop: {e}")
                self._handle_disconnect()

    def _connect_smartly(self):
        strategy = self.strategies[self.current_strategy_index]
        s_name = strategy["name"]
        backend = strategy.get("backend", "ffmpeg")
        
        if strategy["failures"] > 5:
             logger.warning(f"Strategy {s_name} is unstable (5+ failures). Skipping...")
             strategy["failures"] = 0
             self.current_strategy_index = (self.current_strategy_index + 1) % len(self.strategies)
             strategy = self.strategies[self.current_strategy_index]
             s_name = strategy["name"]
             backend = strategy.get("backend", "ffmpeg")
        
        transport_mode = strategy["transport"] 
        
        logger.info(f"Connecting via {s_name} (Attempt {self.reconnect_attempt+1})...")
        
        cap_backend = cv2.CAP_FFMPEG
        source_url = self.rtsp_url

        if backend == "ffmpeg":
            cap_backend = cv2.CAP_FFMPEG
            options = f"rtsp_transport;{transport_mode}"
            if self.fflags: options += f"|fflags;{self.fflags}"
            if self.flags: options += f"|flags;{self.flags}"
            os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = options
            
        elif backend == "gstreamer":
            cap_backend = cv2.CAP_GSTREAMER
            proto = "tcp" if transport_mode == "tcp" else "udp"
            
            source_url = (
                f"rtspsrc location={self.rtsp_url} latency=0 protocols={proto} "
                f"! decodebin ! videoconvert ! appsink max-buffers=1 drop=true"
            )
            logger.info(f"GStreamer Pipeline: {source_url}")
            
        try:
            self.cap = cv2.VideoCapture(source_url, cap_backend)
            if self.cap.isOpened():
                logger.info(f"Connected using {s_name}!")
                if backend == "ffmpeg":
                    self.cap.set(cv2.CAP_PROP_BUFFERSIZE, self.buffer_size) 
                return True
            else:
                logger.warning(f"{s_name} handshake failed.")
                strategy["failures"] += 1
                self._advance_strategy()
                return False
        except Exception as e:
            logger.error(f"{s_name} exception: {e}")
            strategy["failures"] += 1
            self._advance_strategy()
            return False

    def _advance_strategy(self):
        self.current_strategy_index = (self.current_strategy_index + 1) % len(self.strategies)

    def _handle_disconnect(self):
        self.connected = False
        self.reconnect_attempt += 1
        if self.on_disconnect: self.on_disconnect()
        self._release_resources()
        
        delay = self._get_backoff_delay()
        logger.info(f"Disconnected. Backoff {delay}s...")
        time.sleep(delay)

    def _get_backoff_delay(self):
        return min(30.0, 1.5 ** self.reconnect_attempt)

    def _release_resources(self):
        try:
            if self.cap:
                self.cap.release()
        except:
            pass
        finally:
            self.cap = None

    def _update_metrics(self):
        self._fps_counter += 1
        elapsed = time.time() - self._fps_start_time
        if elapsed > 1.0:
            self.fps = self._fps_counter / elapsed
            self._fps_counter = 0
            self._fps_start_time = time.time()

    def read(self):
        with self._lock:
            if self.connected and self._frame_buffer:
                return self._frame_buffer[-1] 
            return None

    def get_metrics(self):
        return {
            "fps": self.fps,
            "dropped": self.dropped_frames,
            "strategy": self.strategies[self.current_strategy_index]["name"],
            "reconnects": self.reconnect_attempt
        }
