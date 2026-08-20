"""
Tracks per-machine cumulative time in each state (running/stopped/uncertain)
based on frame-level classification, and writes a REAL-TIME log file that
is overwritten on every update. Also pushes the current totals to the
FastAPI backend so the database stays in sync, same pattern as recorder.py.
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
        self.totals = self._load_state()

    def _load_state(self):
        if os.path.exists(self.state_path):
            with open(self.state_path, "r") as f:
                return json.load(f)
        return {}

    def _build_state_dict(self):
        state_to_save = {}
        for machine_id, t in self.totals.items():
            runtime = t.get("runtime", 0.0)
            downtime = t.get("downtime", 0.0)
            idle = t.get("idle", 0.0)
            total_available = runtime + downtime + idle
            utilization = (runtime / total_available * 100) if total_available > 0 else 0.0
            state_to_save[machine_id] = {
                "runtime": runtime,
                "downtime": downtime,
                "idle": idle,
                "total_available_time": total_available,
                "total_available_time_formatted": self._format_duration(total_available),
                "utilization_percent": round(utilization, 2),
            }
        return state_to_save

    def _save_state(self):
        state_to_save = self._build_state_dict()
        with open(self.state_path, "w") as f:
            json.dump(state_to_save, f, indent=2)

    def _notify_api(self):
        if not self.api_base_url:
            return
        state_to_send = self._build_state_dict()
        url = f"{self.api_base_url}/api/utilization/sync"
        try:
            response = requests.post(url, json={"data": state_to_send}, timeout=5)
            if response.status_code == 200:
                print(f"[UTILIZATION SYNCED] {len(state_to_send)} machine(s) -> {url}")
            else:
                print(f"[UTILIZATION SYNC FAILED] {response.status_code}: {response.text}")
        except requests.exceptions.RequestException as e:
            print(f"[UTILIZATION SYNC ERROR] Could not reach API: {e}")

    def _ensure_machine(self, machine_id):
        if machine_id not in self.totals:
            self.totals[machine_id] = {"runtime": 0.0, "downtime": 0.0, "idle": 0.0}

    def add_frame(self, machine_id, final_label, frame_duration_sec):
        self._ensure_machine(machine_id)
        if final_label == "running":
            self.totals[machine_id]["runtime"] += frame_duration_sec
        elif final_label == "stopped":
            self.totals[machine_id]["downtime"] += frame_duration_sec
        elif final_label == "uncertain":
            self.totals[machine_id]["idle"] += frame_duration_sec

    def get_summary(self, machine_id):
        self._ensure_machine(machine_id)
        t = self.totals[machine_id]
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

    def _build_line(self, machine_id, now):
        runtime, downtime, idle, total_available, utilization = self.get_summary(machine_id)
        timestamp_str = now.strftime("%Y-%m-%d_%H-%M-%S")
        runtime_h = self._to_hours(runtime)
        downtime_h = self._to_hours(downtime)
        idle_h = self._to_hours(idle)
        total_available_h = self._to_hours(total_available)
        total_available_fmt = self._format_duration(total_available)
        util_pct = round(utilization, 2)

        return (f"{machine_id}_{timestamp_str}_"
                f"Runtime:{runtime_h}h_"
                f"IdleTime:{idle_h}h_"
                f"Downtime:{downtime_h}h_"
                f"TotalAvailableTime:{total_available_h}h ({total_available_fmt})_"
                f"Utilization:{util_pct}%")

    def write_all_logs(self):
        now = datetime.now()
        lines = []

        for machine_id in sorted(self.totals.keys()):
            line = self._build_line(machine_id, now)
            lines.append(line)
            print(f"[UTILIZATION LOGGED] {line}")

        with open(self.log_path, "w") as f:
            f.write("\n".join(lines) + "\n")

        self._save_state()
        self._notify_api()
