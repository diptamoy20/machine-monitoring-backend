"""
Tracks per-machine cumulative time in each state (running/stopped/uncertain),
split by CALENDAR DATE (local time), not cumulative-forever.

Each day gets its own bucket in utilization_state.json:
    {
      "2026-09-07": {"MC-001": {runtime, downtime, idle, ...}, ...},
      "2026-09-08": {"MC-001": {...}, ...}
    }

Today's bucket keeps accumulating live throughout the day. At midnight,
a new bucket automatically starts for the new date - previous days'
numbers are frozen and preserved, enabling calendar-based date lookups
in the Android app.

Only TODAY's bucket is synced to the API/database via /api/utilization/sync,
since the database schema holds one current-state row per machine (not
per-date history) - the full day-wise breakdown lives in this JSON file
and utilization_log.txt on the server, plus /api/utilization/history
(reconstructed from detection_events) for date-range queries via the API.

Mapping:
- "running"   -> Runtime
- "stopped"   -> Downtime
- "uncertain" -> Idle Time (low-confidence frames, below the confidence floor)

Log format (per date, per machine):
{machine_id}_{date}_Runtime:{value}h_IdleTime:{value}h_Downtime:{value}h_TotalAvailableTime:{value}h ({Xh Ym Zs})_Utilization:{value}%
"""

import os
import json
import requests
from datetime import datetime

STATE_FILE_DEFAULT = "utilization_state.json"
LOG_FILE_DEFAULT = "utilization_log.txt"


class UtilizationTracker:
    def __init__(self, state_path=STATE_FILE_DEFAULT, log_path=LOG_FILE_DEFAULT, api_base_url=None):
        self.state_path = state_path
        self.log_path = log_path
        self.api_base_url = api_base_url
        self.daily_totals = self._load_state()

    def _load_state(self):
        """
        Loads existing day-wise state. If the file is in the OLD
        cumulative-forever format (top-level keys are machine IDs like
        "MC-001" rather than dates), it's discarded and tracking starts
        fresh - old format is incompatible with day-wise bucketing.
        """
        if os.path.exists(self.state_path):
            try:
                with open(self.state_path, "r") as f:
                    data = json.load(f)
                if data:
                    first_key = next(iter(data))
                    if first_key.startswith("MC-"):
                        print("[UTILIZATION] Old cumulative-format state file detected - discarding, starting fresh day-wise tracking.")
                        return {}
                return data
            except (json.JSONDecodeError, StopIteration):
                return {}
        return {}

    def _today_str(self):
        return datetime.now().strftime("%Y-%m-%d")

    def _ensure_machine(self, date_str, machine_id):
        self.daily_totals.setdefault(date_str, {})
        self.daily_totals[date_str].setdefault(machine_id, {"runtime": 0.0, "downtime": 0.0, "idle": 0.0})

    def add_frame(self, machine_id, final_label, frame_duration_sec):
        date_str = self._today_str()
        self._ensure_machine(date_str, machine_id)
        bucket = self.daily_totals[date_str][machine_id]
        if final_label == "running":
            bucket["runtime"] += frame_duration_sec
        elif final_label == "stopped":
            bucket["downtime"] += frame_duration_sec
        elif final_label == "uncertain":
            bucket["idle"] += frame_duration_sec

    def get_summary(self, date_str, machine_id):
        self._ensure_machine(date_str, machine_id)
        t = self.daily_totals[date_str][machine_id]
        runtime, downtime, idle = t["runtime"], t["downtime"], t["idle"]
        total_available = runtime + downtime + idle
        utilization = (runtime / total_available * 100) if total_available > 0 else 0.0
        return runtime, downtime, idle, total_available, utilization

    @staticmethod
    def _to_hours(seconds):
        return round(seconds / 3600, 3)

    @staticmethod
    def _format_duration(seconds):
        total_seconds = int(round(seconds))
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        secs = total_seconds % 60
        return f"{hours}h {minutes}m {secs}s"

    def _build_full_state_dict(self):
        result = {}
        for date_str, machines in self.daily_totals.items():
            result[date_str] = {}
            for machine_id in machines:
                runtime, downtime, idle, total_available, utilization = self.get_summary(date_str, machine_id)
                result[date_str][machine_id] = {
                    "runtime": runtime,
                    "downtime": downtime,
                    "idle": idle,
                    "total_available_time": total_available,
                    "total_available_time_formatted": self._format_duration(total_available),
                    "utilization_percent": round(utilization, 2),
                }
        return result

    def _save_state(self):
        state = self._build_full_state_dict()
        with open(self.state_path, "w") as f:
            json.dump(state, f, indent=2)

    def _notify_api(self):
        """Sync only TODAY's bucket - the DB holds current-state, not per-date history."""
        if not self.api_base_url:
            return
        date_str = self._today_str()
        full_state = self._build_full_state_dict()
        today_data = full_state.get(date_str, {})
        if not today_data:
            return

        url = f"{self.api_base_url}/api/utilization/sync"
        try:
            response = requests.post(url, json={"data": today_data}, timeout=20)
            if response.status_code == 200:
                print(f"[UTILIZATION SYNCED] {len(today_data)} machine(s) for {date_str} -> {url}")
            else:
                print(f"[UTILIZATION SYNC FAILED] {response.status_code}: {response.text}")
        except requests.exceptions.RequestException as e:
            print(f"[UTILIZATION SYNC ERROR] Could not reach API: {e}")

    def write_all_logs(self):
        state = self._build_full_state_dict()
        lines = []

        for date_str in sorted(state.keys()):
            lines.append(f"=== {date_str} ===")
            for machine_id in sorted(state[date_str].keys()):
                d = state[date_str][machine_id]
                line = (f"{machine_id}_{date_str}_"
                        f"Runtime:{self._to_hours(d['runtime'])}h_"
                        f"IdleTime:{self._to_hours(d['idle'])}h_"
                        f"Downtime:{self._to_hours(d['downtime'])}h_"
                        f"TotalAvailableTime:{self._to_hours(d['total_available_time'])}h ({d['total_available_time_formatted']})_"
                        f"Utilization:{d['utilization_percent']}%")
                lines.append(line)
                print(f"[UTILIZATION LOGGED] {line}")
            lines.append("")

        with open(self.log_path, "w") as f:
            f.write("\n".join(lines) + "\n")

        self._save_state()
        self._notify_api()
