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
        data = {}
        if os.path.exists(self.state_path):
            try:
                with open(self.state_path, "r") as f:
                    loaded = json.load(f)
                if loaded:
                    first_key = next(iter(loaded))
                    if first_key.startswith("MC-"):
                        print("[UTILIZATION] Old-format state file detected - discarding, starting fresh.")
                        loaded = {}
                    else:
                        sample_date = next(iter(loaded.values()), {})
                        if sample_date:
                            sample_machine = next(iter(sample_date.values()), {})
                            if "offline" not in sample_machine:
                                print("[UTILIZATION] Old schema (no offline bucket) detected - discarding, starting fresh.")
                                loaded = {}
                data = loaded or {}
            except (json.JSONDecodeError, StopIteration):
                data = {}

        # Self-healing synchronization with Database API:
        # Check if the database has higher or existing numbers for today.
        # This prevents a stale local file from overwriting database updates!
        if self.api_base_url:
            today_str = self._today_str()
            try:
                resp = requests.get(f"{self.api_base_url}/api/utilization", timeout=5)
                if resp.status_code == 200:
                    db_items = resp.json()
                    data.setdefault(today_str, {})
                    for row in db_items:
                        if str(row.get("date")) == today_str:
                            mc = row.get("mc_id")
                            if not mc:
                                continue
                            db_run = float(row.get("runtime") or 0.0)
                            db_down = float(row.get("downtime") or 0.0)
                            db_un = float(row.get("undetected_time") or 0.0)

                            local_mc = data[today_str].get(mc, {})
                            local_run = float(local_mc.get("runtime") or 0.0)

                            # If DB has greater or equal runtime, or local machine is missing, adopt DB values
                            if db_run >= local_run or mc not in data[today_str]:
                                data[today_str][mc] = {
                                    "runtime": db_run,
                                    "downtime": db_down,
                                    "offline": db_un,
                                    "undetected": 0.0,
                                }
                    print(f"[UTILIZATION] Verified and synced memory state with DB for {today_str}.")
            except Exception as e:
                print(f"[UTILIZATION] DB pre-sync skipped (API unreachable): {e}")

        return data

    def _today_str(self):
        return datetime.now().strftime("%Y-%m-%d")

    def _ensure_machine(self, date_str, machine_id):
        self.daily_totals.setdefault(date_str, {})
        self.daily_totals[date_str].setdefault(
            machine_id, {"runtime": 0.0, "downtime": 0.0, "offline": 0.0, "undetected": 0.0}
        )

    def add_frame(self, machine_id, final_label, dt_seconds):
        date_str = self._today_str()
        self._ensure_machine(date_str, machine_id)
        bucket = self.daily_totals[date_str][machine_id]
        # ensure backward-compat for state files loaded without undetected key
        bucket.setdefault("undetected", 0.0)

        if final_label == "running":
            bucket["runtime"] += dt_seconds
        elif final_label == "stopped":
            bucket["downtime"] += dt_seconds
        elif final_label == "offline":
            bucket["offline"] += dt_seconds
        elif final_label == "uncertain":
            bucket["undetected"] += dt_seconds   # low-confidence = undetected

    def get_summary(self, date_str, machine_id):
        self._ensure_machine(date_str, machine_id)
        t = self.daily_totals[date_str][machine_id]
        runtime  = t["runtime"]
        downtime = t["downtime"]
        offline  = t["offline"]
        undetected = t.get("undetected", 0.0)

        total_available = runtime + downtime
        utilization = (runtime / total_available * 100) if total_available > 0 else 0.0

        return runtime, downtime, offline, undetected, total_available, utilization

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
                runtime, downtime, offline, undetected, total_available, utilization = self.get_summary(date_str, machine_id)
                result[date_str][machine_id] = {
                    "runtime": round(runtime, 2),
                    "downtime": round(downtime, 2),
                    "offline": round(offline, 2),
                    "undetected": round(undetected, 2),
                    "undetected_time": round(offline + undetected, 2),
                    "offline_time": round(offline, 2),
                    "total_available_time": round(total_available, 2),
                    "total_available_time_formatted": self._format_duration(total_available),
                    "total_time": round(total_available + offline, 2),
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
                print(f"[UTILIZATION SYNC FAILED] HTTP {response.status_code}: {response.text[:500]}")
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
