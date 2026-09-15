import logging
from typing import List, Dict, Any, Optional
from datetime import datetime
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

router = APIRouter(tags=["live_stream"])


class LiveConnectionManager:
    """Manages active WebSocket connections and broadcasts live machine/camera telemetry."""

    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.latest_state: Dict[str, Any] = {
            "type": "initial_state",
            "last_updated": None,
            "machines": {},
            "cameras": {},
        }

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"[WS LIVE] Client connected. Total active: {len(self.active_connections)}")
        # Send latest snapshot immediately upon connection if available
        if self.latest_state.get("last_updated"):
            try:
                await websocket.send_json(self.latest_state)
            except Exception as e:
                logger.warning(f"[WS LIVE] Failed to send initial snapshot: {e}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info(f"[WS LIVE] Client disconnected. Remaining active: {len(self.active_connections)}")

    async def broadcast(self, data: Dict[str, Any], exclude: Optional[WebSocket] = None):
        """Broadcasts data to all connected clients except optional sender."""
        disconnected = []
        for connection in self.active_connections:
            if connection is not exclude:
                try:
                    await connection.send_json(data)
                except Exception as e:
                    logger.warning(f"[WS LIVE] Error sending to client: {e}")
                    disconnected.append(connection)

        for conn in disconnected:
            self.disconnect(conn)

    def update_latest_state(self, payload: Dict[str, Any]):
        """Merges incoming payload into cached state."""
        self.latest_state["last_updated"] = payload.get("timestamp") or datetime.now().isoformat()
        if "machines" in payload:
            self.latest_state["machines"].update(payload["machines"])
        if "cameras" in payload:
            self.latest_state["cameras"].update(payload["cameras"])


manager = LiveConnectionManager()


@router.websocket("/ws/live")
async def live_data_websocket(websocket: WebSocket):
    """
    Bi-directional live data WebSocket:
    - main_live.py publishes live telemetry here (machines, cameras, utilization).
    - Web dashboards and viewers subscribe to receive real-time updates.
    """
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_json()
            # Cache incoming state & broadcast to all connected viewers
            manager.update_latest_state(data)
            await manager.broadcast(data, exclude=websocket)
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.warning(f"[WS LIVE] Error in WebSocket loop: {e}")
        manager.disconnect(websocket)


@router.get("/api/live/snapshot", summary="Get latest live telemetry snapshot")
def get_live_snapshot():
    """Returns the latest in-memory live telemetry snapshot without waiting for WebSocket."""
    return manager.latest_state
