import requests
from datetime import datetime, timezone
import traceback

class OfflineSessionTracker:
    def __init__(self, api_base_url):
        self.api_base_url = api_base_url
        
    def _post_session(self, channel_key, cam_ip, went_offline_at, came_online_at=None, duration_seconds=None):
        if not self.api_base_url:
            return
            
        url = f"{self.api_base_url}/api/camera-sessions/offline"
        
        payload = {
            "channel_key": channel_key,
            "cam_ip": cam_ip,
            "went_offline_at": went_offline_at.isoformat(),
        }
        
        if came_online_at:
            payload["came_online_at"] = came_online_at.isoformat()
        if duration_seconds is not None:
            payload["duration_seconds"] = duration_seconds
            
        try:
            res = requests.post(url, json=payload, timeout=10)
            if res.status_code != 200:
                print(f"[OFFLINE SESSION ERROR] Failed to record session: {res.text}")
            else:
                status = "OPENED" if not came_online_at else "CLOSED"
                print(f"[OFFLINE SESSION {status}] {channel_key}")
        except Exception as e:
            print(f"[OFFLINE SESSION EXCEPTION] {e}")

    def mark_offline(self, channel_key, cam_ip, timestamp=None):
        if not timestamp:
            timestamp = datetime.now(timezone.utc)
        else:
            timestamp = datetime.fromtimestamp(timestamp, timezone.utc)
            
        # We fire and forget
        self._post_session(channel_key, cam_ip, timestamp)
        
    def mark_online(self, channel_key, cam_ip, offline_since_timestamp, current_timestamp=None):
        if not current_timestamp:
            current_timestamp = datetime.now(timezone.utc)
        else:
            current_timestamp = datetime.fromtimestamp(current_timestamp, timezone.utc)
            
        if not offline_since_timestamp:
            print(f"[OFFLINE SESSION WARNING] No offline_since_timestamp provided for {channel_key}")
            return
            
        went_offline_at = datetime.fromtimestamp(offline_since_timestamp, timezone.utc)
        duration = (current_timestamp - went_offline_at).total_seconds()
        
        self._post_session(channel_key, cam_ip, went_offline_at, current_timestamp, duration)
