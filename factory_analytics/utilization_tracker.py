import os
import json
import requests
from datetime import datetime

STATE_FILE_DEFAULT = "utilization_state.json"
LOG_FILE_DEFAULT = "utilization_log.txt"


class UtilizationTracker:
    def __init__(self, state_path=STATE_FILE_DEFAULT, log_path=LOG_FILE_DEFAULT, api_base_url=None, undetected_log_path=None):
        self.state_path = state_path
        self.log_path = log_path
        self.api_base_url = api_base_url
        self.undetected_log_path = undetected_log_path
        self.daily_totals = self._load_state()

    def _load_state(self):
        if os.path.exists(self.state_path):
            try:
                with open(self.state_path, "r") as f:
                    data = json.load(f)
                if data:
                    first_key = next(iter(data))
                    if first_key.startswith("MC-"):
                        print("[UTILIZATION] Old-format state file detected - discarding, starting fresh.")
                        return {}
                    sample_date = next(iter(data.values()))
                    if sample_date:
                        sample_machine = next(iter(sample_date.values()))
                        if "offline" not in sample_machine:
                            print("[UTILIZATION] Old schema (no offline bucket) detected - discarding, starting fresh.")
                            return {}
                return data
            except (json.JSONDecodeError, StopIteration):
                return {}
        return {}

    def _today_str(self):
        return datetime.now().strftime("%Y-%m-%d")

    def _ensure_machine(self, date_str, machine_id):
        self.daily_totals.setdefault(date_str, {})
        self.daily_totals[date_str].setdefault(
            machine_id, {"runtime": 0.0, "downtime": 0.0, "offline": 0.0}
        )

    def add_frame(self, machine_id, final_label, dt_seconds):
        date_str = self._today_str()
        self._ensure_machine(date_str, machine_id)
        bucket = self.daily_totals[date_str][machine_id]

        if final_label == "running":
            bucket["runtime"] += dt_seconds
        elif final_label == "stopped":
            bucket["downtime"] += dt_seconds
        elif final_label == "offline":
            bucket["offline"] += dt_seconds

    def get_summary(self, date_str, machine_id):
        self._ensure_machine(date_str, machine_id)
        t = self.daily_totals[date_str][machine_id]
        runtime, downtime, offline = t["runtime"], t["downtime"], t["offline"]

        total_available = runtime + downtime
        utilization = (runtime / total_available * 100) if total_available > 0 else 0.0

        return runtime, downtime, offline, total_available, utilization

    @staticmethod
    def _to_hours(seconds):
        return round(seconds / 3600, 2)

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
                runtime, downtime, offline, total_available, utilization = self.get_summary(date_str, machine_id)
                result[date_str][machine_id] = {
                    "runtime": round(runtime, 2),
                    "downtime": round(downtime, 2),
                    "offline": round(offline, 2),
                    "total_available_time": round(total_available, 2),
                    "total_available_time_formatted": self._format_duration(total_available),
                    "utilization_percent": round(utilization, 2),
                }
        return result

    def _save_state(self):
        state = self._build_full_state_dict()
        with open(self.state_path, "w") as f:
            json.dump(state, f, indent=2)

    def _notify_api(self):
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
                h_run = self._to_hours(d["runtime"])
                h_down = self._to_hours(d["downtime"])
                h_offline = self._to_hours(d["offline"])
                h_available = h_run + h_down
                sanity_total = h_run + h_down + h_offline

                line = (f"{machine_id}_{date_str}_"
                        f"Runtime:{h_run}h_"
                        f"Downtime:{h_down}h_"
                        f"Offline:{h_offline}h_"
                        f"TotalAvailableTime:{h_available}h ({d['total_available_time_formatted']})_"
                        f"Utilization:{d['utilization_percent']}%_"
                        f"SanityCheck(~24h):{round(sanity_total, 2)}h")
                lines.append(line)
                print(f"[UTILIZATION LOGGED] {line}")
            lines.append("")

        with open(self.log_path, "w") as f:
            f.write("\n".join(lines) + "\n")

        self._write_undetected_log(state)
        self._save_state()
        self._notify_api()

    def _write_undetected_log(self, state):
        if not self.undetected_log_path:
            return

        lines = []
        for date_str in sorted(state.keys()):
            lines.append(f"=== {date_str} ===")
            for machine_id in sorted(state[date_str].keys()):
                d = state[date_str][machine_id]
                undetected_formatted = self._format_duration(d["offline"])
                line = f"{machine_id}_{date_str}_UndetectedTime:{undetected_formatted}"
                lines.append(line)
            lines.append("")

        try:
            with open(self.undetected_log_path, "w") as f:
                f.write("\n".join(lines) + "\n")
        except Exception as e:
            print(f"[UNDETECTED LOG ERROR] {e}")
