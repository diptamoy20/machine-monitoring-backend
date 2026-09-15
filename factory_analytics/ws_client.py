import json
import time
import queue
import logging
import threading
from typing import Dict, Any, Optional
import websocket

logger = logging.getLogger("LiveWebSocketClient")


class LiveWebSocketClient:
    """
    Resilient, non-blocking WebSocket publisher for main_live.py:
    - Operates in a dedicated background daemon thread.
    - Sends machine statuses, metrics, camera health to backend /ws/live.
    - Automatically reconnects if backend restarts or drops connection.
    - Uses a bounded queue to drop stale messages and never block video processing.
    """

    def __init__(self, api_base_url: str = "http://localhost:8000", queue_maxsize: int = 20):
        # Convert http(s) URL to ws(s) WebSocket URL
        base = api_base_url.rstrip("/")
        if base.startswith("https://"):
            ws_base = "wss://" + base[8:]
        elif base.startswith("http://"):
            ws_base = "ws://" + base[7:]
        else:
            ws_base = "ws://" + base

        self.ws_url = f"{ws_base}/ws/live"
        self.queue = queue.Queue(maxsize=queue_maxsize)
        self.running = False
        self.connected = False
        self.thread: Optional[threading.Thread] = None
        self._ws: Optional[websocket.WebSocket] = None
        self._lock = threading.Lock()

    def start(self):
        """Starts the background sender thread."""
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._run_loop, name="WS-Live-Publisher", daemon=True)
        self.thread.start()
        print(f"[WS CLIENT] Live WebSocket publisher started targeting {self.ws_url}")

    def stop(self):
        """Stops the sender thread cleanly."""
        self.running = False
        with self._lock:
            if self._ws:
                try:
                    self._ws.close()
                except Exception:
                    pass
                self._ws = None
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2.0)
        print("[WS CLIENT] Live WebSocket publisher stopped.")

    def send_live_data(self, payload: Dict[str, Any]):
        """
        Enqueues payload for non-blocking transmission.
        If queue is full, drops oldest frame to ensure zero lag.
        """
        if not self.running:
            return
        if self.queue.full():
            try:
                self.queue.get_nowait()
            except queue.Empty:
                pass
        try:
            self.queue.put_nowait(payload)
        except queue.Full:
            pass

    def _run_loop(self):
        """Worker loop maintaining connection and draining queue."""
        reconnect_delay = 2.0

        while self.running:
            ws = None
            try:
                # Attempt connection with 4-second timeout
                ws = websocket.create_connection(self.ws_url, timeout=4.0)
                with self._lock:
                    self._ws = ws
                    self.connected = True
                print(f"[WS CLIENT] Connected to live backend at {self.ws_url}")
                reconnect_delay = 2.0

                # Transmission loop while connected
                while self.running and self.connected:
                    try:
                        payload = self.queue.get(timeout=0.5)
                    except queue.Empty:
                        continue

                    try:
                        msg = json.dumps(payload)
                        ws.send(msg)
                    except (websocket.WebSocketException, OSError) as e:
                        logger.warning(f"[WS CLIENT] Send error, reconnecting: {e}")
                        break

            except (websocket.WebSocketException, OSError, ConnectionRefusedError) as e:
                # Backend is offline or unreachable - retry without crashing
                with self._lock:
                    self.connected = False
                    self._ws = None
                time.sleep(reconnect_delay)
                reconnect_delay = min(10.0, reconnect_delay * 1.5)

            finally:
                with self._lock:
                    self.connected = False
                    if ws:
                        try:
                            ws.close()
                        except Exception:
                            pass
                        self._ws = None
