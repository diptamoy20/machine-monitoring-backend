"""
WebSocket-based ROI editor for live RTSP camera streams.

Browser-based replacement for the OpenCV desktop tool (select_roi_rtsp.py).
The roi_config.json output format is IDENTICAL — the same ROIManager.save_rois_for_key()
call is made with the same polygon structure:
  [{"shape": "polygon", "points": [[x, y], ...], "machine_id": "MC-XXX"}, ...]

Endpoints:
  GET    /roi-editor                        → serves the HTML editor page
  GET    /roi-editor/channels               → list cameras + ROI status
  DELETE /roi-editor/channels/{channel_key} → clear saved ROI for one channel
  WS     /ws/roi-editor/{channel_key}       → interactive drawing session

WebSocket message protocol
--------------------------
Client → Server (JSON text):
  {"type": "add_point",      "x": 455, "y": 324}
  {"type": "undo_point"}
  {"type": "close_polygon",  "machine_id": "MC-001"}
  {"type": "reset_polygon"}
  {"type": "delete_polygon", "index": 0}
  {"type": "save"}
  {"type": "skip"}

Server → Client:
  Binary (first message):  raw JPEG bytes of the frozen frame
  JSON:  {"type": "status",       "message": "..."}
  JSON:  {"type": "state",        "current_points": [...], "completed": [...],
                                  "machine_ids": [...], "frame_width": N,
                                  "frame_height": N, "channel_key": "...",
                                  "had_existing_roi": bool}
  JSON:  {"type": "saved",        "channel_key": "...", "count": N, "machine_ids": [...]}
  JSON:  {"type": "skipped",      "channel_key": "..."}
  JSON:  {"type": "error",        "message": "..."}
  JSON:  {"type": "frame_failed", "message": "..."}
"""

import sys
import os
import json
import asyncio
import logging
from typing import Optional

import cv2
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse

# ── Make factory_analytics importable from this route ──────────────────────────
# The FastAPI app is launched from the project root, but factory_analytics is a
# sibling directory of `app/`.  Inserting it into sys.path lets us reuse all
# existing logic (config, ROIManager, channel_key_from_url) without copying code.
_FA_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "factory_analytics")
)
if _FA_DIR not in sys.path:
    sys.path.insert(0, _FA_DIR)

import config as fa_config                        # noqa: E402  (factory_analytics/config.py)
from roi_manager import ROIManager                # noqa: E402  (factory_analytics/roi_manager.py)
from select_roi_rtsp import channel_key_from_url  # noqa: E402  (factory_analytics/select_roi_rtsp.py)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["ROI Editor"])

_HTML_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "static", "roi_editor.html")
)

# How long (seconds) to wait for the RTSP frame grab before giving up
_FRAME_GRAB_TIMEOUT = 20.0
# How many cap.read() attempts before accepting a frame
_FRAME_GRAB_ATTEMPTS = 5


# ── Helpers ────────────────────────────────────────────────────────────────────

def _url_for_channel(channel_key: str) -> Optional[str]:
    """Return the RTSP URL whose channel parameter matches channel_key, or None."""
    for url in fa_config.RTSP_URLS:
        if channel_key_from_url(url) == channel_key:
            return url
    return None


def _grab_frame_sync(url: str) -> Optional[tuple]:
    """
    Blocking RTSP frame grab — always run via asyncio.to_thread() to avoid
    blocking the FastAPI event loop.

    Returns (jpeg_bytes: bytes, width: int, height: int) on success, None on failure.
    """
    cap = cv2.VideoCapture(url)
    frame = None

    if cap.isOpened():
        for _ in range(_FRAME_GRAB_ATTEMPTS):
            ret, f = cap.read()
            if ret and f is not None:
                frame = f
                break

    cap.release()

    if frame is None:
        return None

    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok:
        return None

    return buf.tobytes(), int(frame.shape[1]), int(frame.shape[0])


# ── HTTP endpoints ─────────────────────────────────────────────────────────────

@router.get("/roi-editor", response_class=HTMLResponse, summary="ROI Editor UI")
async def roi_editor_page():
    """Serve the browser-based ROI editor page."""
    with open(_HTML_PATH, encoding="utf-8") as f:
        return f.read()


@router.get("/roi-editor/channels", summary="List camera channels and ROI status")
async def list_channels():
    """
    Return all configured RTSP channels with their current ROI status.
    Used by the UI to populate the camera selector and show which channels
    already have ROIs configured.
    """
    roi_manager = ROIManager(fa_config.ROI_CONFIG_PATH, valid_machine_ids=fa_config.MACHINE_IDS)
    result = []
    for url in fa_config.RTSP_URLS:
        key = channel_key_from_url(url)
        existing = roi_manager.all_config.get(key, [])
        result.append({
            "key": key,
            "has_roi": len(existing) > 0,
            "roi_count": len(existing),
            "polygon_machine_ids": [r["machine_id"] for r in existing],
        })
    return result


@router.delete(
    "/roi-editor/channels/{channel_key}",
    summary="Clear saved ROI for a channel",
)
async def clear_channel_roi(channel_key: str):
    """
    Delete the saved ROI config for a specific channel so it can be redrawn.
    Equivalent to manually removing the entry from roi_config.json.
    """
    roi_manager = ROIManager(fa_config.ROI_CONFIG_PATH, valid_machine_ids=fa_config.MACHINE_IDS)
    if channel_key not in roi_manager.all_config:
        return JSONResponse(
            status_code=404,
            content={"detail": f"No ROI found for channel '{channel_key}'"},
        )
    del roi_manager.all_config[channel_key]
    roi_manager._save()
    logger.info(f"[ROI Editor] Cleared ROI for {channel_key}")
    return {"deleted": channel_key}


# ── WebSocket endpoint ─────────────────────────────────────────────────────────

@router.websocket("/ws/roi-editor/{channel_key}")
async def roi_editor_ws(websocket: WebSocket, channel_key: str):
    """
    One WebSocket session per camera ROI-drawing interaction.

    Flow:
      1. Validate the channel exists in fa_config.RTSP_URLS
      2. Grab a single JPEG frame from the RTSP stream (non-blocking via thread)
      3. Send the frame as binary, then send the initial state as JSON
      4. Loop: receive commands, update in-memory polygon state, send back new state
      5. On "save": call ROIManager.save_rois_for_key() — identical to select_roi_rtsp.py
    """
    await websocket.accept()

    # ── 1. Validate channel ────────────────────────────────────────────────────
    url = _url_for_channel(channel_key)
    if url is None:
        await websocket.send_json({
            "type": "error",
            "message": f"Unknown channel key: '{channel_key}'. Check fa_config.RTSP_URLS.",
        })
        await websocket.close()
        return

    # ── 2. Grab frame (non-blocking) ──────────────────────────────────────────
    await websocket.send_json({
        "type": "status",
        "message": f"Connecting to {channel_key} RTSP stream…",
    })

    try:
        grab_result = await asyncio.wait_for(
            asyncio.to_thread(_grab_frame_sync, url),
            timeout=_FRAME_GRAB_TIMEOUT,
        )
    except asyncio.TimeoutError:
        await websocket.send_json({
            "type": "frame_failed",
            "message": (
                f"Timed out after {_FRAME_GRAB_TIMEOUT:.0f}s connecting to {channel_key}. "
                "The camera may be offline or unreachable."
            ),
        })
        await websocket.close()
        return
    except Exception as exc:
        await websocket.send_json({
            "type": "frame_failed",
            "message": f"Error grabbing frame: {exc}",
        })
        await websocket.close()
        return

    if grab_result is None:
        await websocket.send_json({
            "type": "frame_failed",
            "message": (
                f"Could not read a frame from {channel_key}. "
                "Camera may be offline or RTSP credentials may have changed."
            ),
        })
        await websocket.close()
        return

    jpeg_bytes, frame_w, frame_h = grab_result

    # ── 3. Send JPEG frame as binary ──────────────────────────────────────────
    await websocket.send_bytes(jpeg_bytes)

    # ── 4. Initialise state from existing ROI config (if any) ─────────────────
    roi_manager = ROIManager(fa_config.ROI_CONFIG_PATH, valid_machine_ids=fa_config.MACHINE_IDS)
    existing_rois: list = list(roi_manager.all_config.get(channel_key, []))

    current_points: list = []
    completed: list = list(existing_rois)   # pre-populate so user can see existing ROIs

    async def send_state():
        """Push the full current polygon state to the browser."""
        await websocket.send_json({
            "type": "state",
            "current_points": current_points,
            "completed": completed,
            "machine_ids": fa_config.MACHINE_IDS,
            "frame_width": frame_w,
            "frame_height": frame_h,
            "channel_key": channel_key,
            "had_existing_roi": len(existing_rois) > 0,
        })

    await send_state()

    # ── 5. Command loop ────────────────────────────────────────────────────────
    try:
        while True:
            raw = await websocket.receive_text()

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "message": "Invalid JSON received."})
                continue

            msg_type = msg.get("type")

            # ── add_point ──────────────────────────────────────────────────────
            if msg_type == "add_point":
                try:
                    current_points.append([int(msg["x"]), int(msg["y"])])
                except (KeyError, ValueError):
                    await websocket.send_json({"type": "error", "message": "add_point requires integer x and y."})
                    continue
                await send_state()

            # ── undo_point ─────────────────────────────────────────────────────
            elif msg_type == "undo_point":
                if current_points:
                    current_points.pop()
                await send_state()

            # ── close_polygon ──────────────────────────────────────────────────
            elif msg_type == "close_polygon":
                if len(current_points) < 3:
                    await websocket.send_json({
                        "type": "error",
                        "message": f"Need at least 3 points to close a polygon (have {len(current_points)}).",
                    })
                    continue

                machine_id = msg.get("machine_id", "").strip()
                if machine_id not in fa_config.MACHINE_IDS:
                    await websocket.send_json({
                        "type": "error",
                        "message": f"Invalid machine ID '{machine_id}'. Must be one of: {fa_config.MACHINE_IDS}",
                    })
                    continue

                # ── This is the SAME structure that select_roi_rtsp.py produces ──
                completed.append({
                    "shape": "polygon",
                    "points": current_points.copy(),
                    "machine_id": machine_id,
                })
                current_points = []
                await send_state()

            # ── reset_polygon ──────────────────────────────────────────────────
            elif msg_type == "reset_polygon":
                current_points = []
                await send_state()

            # ── delete_polygon ─────────────────────────────────────────────────
            elif msg_type == "delete_polygon":
                try:
                    idx = int(msg.get("index", -1))
                    if 0 <= idx < len(completed):
                        completed.pop(idx)
                    else:
                        await websocket.send_json({"type": "error", "message": f"No polygon at index {idx}."})
                        continue
                except (ValueError, TypeError):
                    await websocket.send_json({"type": "error", "message": "delete_polygon requires an integer index."})
                    continue
                await send_state()

            # ── save ───────────────────────────────────────────────────────────
            elif msg_type == "save":
                if not completed:
                    await websocket.send_json({
                        "type": "error",
                        "message": "No polygons drawn yet. Draw at least one polygon before saving.",
                    })
                    continue

                # ── Identical call to what select_roi_rtsp.py does ─────────────
                roi_manager.save_rois_for_key(channel_key, completed)
                logger.info(
                    f"[ROI Editor] Saved {len(completed)} polygon(s) for {channel_key}: "
                    f"{[p['machine_id'] for p in completed]}"
                )
                await websocket.send_json({
                    "type": "saved",
                    "channel_key": channel_key,
                    "count": len(completed),
                    "machine_ids": [p["machine_id"] for p in completed],
                })
                break   # session complete

            # ── skip ───────────────────────────────────────────────────────────
            elif msg_type == "skip":
                logger.info(f"[ROI Editor] Skipped {channel_key} — no ROIs saved.")
                await websocket.send_json({"type": "skipped", "channel_key": channel_key})
                break   # session complete

            else:
                logger.warning(f"[ROI Editor] Unknown message type '{msg_type}' from client.")

    except WebSocketDisconnect:
        logger.info(f"[ROI Editor] Client disconnected from session: {channel_key}")

    except Exception as exc:
        logger.exception(f"[ROI Editor] Unexpected error in session for {channel_key}: {exc}")
        try:
            await websocket.send_json({"type": "error", "message": f"Server error: {exc}"})
        except Exception:
            pass
