"""
repair_today_utilization.py
----------------------------
Run this ONCE on your local machine (or the server) while the main-live.service
is STOPPED.

It reads all detection_events for today, reconstructs the correct
runtime / downtime / undetected_time from the raw timeline, and writes
the result directly into machine_utilization for today's date.

Usage (in the project root with venv activated):
    .\\venv312\\Scripts\\python.exe repair_today_utilization.py

After running this, start the service again on the server:
    sudo systemctl start main-live.service
"""

import sys
import json
from datetime import datetime, timezone, timedelta, date
from zoneinfo import ZoneInfo
from collections import defaultdict

from sqlalchemy.orm import Session
from app.database.connection import SessionLocal
from app.database.models import DetectionEvent, MachineUtilization

TARGET_DATE = datetime.now(timezone.utc).date()

# Use IST (UTC+5:30) so the day starts at 00:00 IST = 18:30 UTC previous day
# This ensures 'total time' = 16h 15m (midnight IST to now) not just 10h 45m.
IST = ZoneInfo("Asia/Kolkata")

def hms(seconds):
    total = int(round(seconds))
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    return f"{h}h {m}m {s}s"

def repair(db: Session):
    # Day starts at 00:00 IST, not 00:00 UTC
    # 00:00 IST = 18:30 UTC the previous calendar day
    today_ist = datetime.now(IST).date()
    start_of_day = datetime(today_ist.year, today_ist.month, today_ist.day,
                            0, 0, 0, tzinfo=IST).astimezone(timezone.utc)
    end_of_day = start_of_day + timedelta(days=1)
    print(f"[REPAIR] Day window (IST): {start_of_day.astimezone(IST)} --> {end_of_day.astimezone(IST)}")

    state_dict = {}
    today_str = today_ist.strftime("%Y-%m-%d")
    state_dict[today_str] = {}

    events = (
        db.query(DetectionEvent)
        .filter(
            DetectionEvent.detected_at >= start_of_day,
            DetectionEvent.detected_at < end_of_day,
        )
        .order_by(DetectionEvent.mc_id, DetectionEvent.detected_at.asc())
        .all()
    )

    if not events:
        print(f"[REPAIR] No detection events found for {TARGET_DATE}.")
        print("         Cannot reconstruct — today's raw event data is empty.")
        return

    by_machine = defaultdict(list)
    for e in events:
        by_machine[e.mc_id].append(e)

    now_utc = datetime.now(timezone.utc)

    for mc_id, evts in sorted(by_machine.items()):
        # Find when the machine actually started working today (morning shift start)
        # Shift events are from when work begins in the morning (~07:50 - 08:05 AM)
        shift_evts = [
            e for e in evts
            if e.detected_at.astimezone(IST).hour >= 7
            and (e.detected_at.astimezone(IST).hour > 7 or e.detected_at.astimezone(IST).minute >= 50)
        ]

        if shift_evts:
            start_work_time = shift_evts[0].detected_at
            active_events = shift_evts
        else:
            start_work_time = evts[0].detected_at
            active_events = evts

        # Time before the machine started working (from 12:00 AM to start_work_time)
        # Machine was stopped / not working before morning start -> DOWNTIME
        pre_start_downtime = max(0.0, (start_work_time - start_of_day).total_seconds())

        # Runtime and downtime during active working period
        work_runtime = 0.0
        work_downtime = 0.0

        for i in range(len(active_events)):
            seg_start = active_events[i].detected_at
            seg_end = active_events[i + 1].detected_at if i + 1 < len(active_events) else now_utc
            duration = max(0.0, (seg_end - seg_start).total_seconds())

            if active_events[i].status.lower() in ("running",):
                work_runtime += duration
            elif active_events[i].status.lower() in ("stopped", "stop"):
                work_downtime += duration

        # Undetected time during working hours (camera drops / low confidence)
        undetected_candidates = [
            (e.undetected_time or 0.0) for e in active_events
            if (e.undetected_time or 0.0) < 1000.0
        ]
        shift_undetected = max(undetected_candidates) if undetected_candidates else 15.0

        runtime = work_runtime
        downtime = pre_start_downtime + work_downtime
        total_available = runtime + downtime
        utilization = (runtime / total_available * 100) if total_available > 0 else 0.0

        print(f"\n[{mc_id}]")
        print(f"  Started working at : {start_work_time.astimezone(IST).strftime('%H:%M:%S IST')}")
        print(f"  Pre-start downtime : {hms(pre_start_downtime)}  ({round(pre_start_downtime, 1)}s)")
        print(f"  Runtime (working)  : {hms(runtime)}  ({round(runtime, 1)}s)")
        print(f"  Downtime (total)   : {hms(downtime)}  ({round(downtime, 1)}s)")
        print(f"  Total time (24h)   : {hms(total_available)}  ({round(total_available, 1)}s)")
        print(f"  Utilization        : {round(utilization, 2)}%")
        print(f"  Undetected         : {round(shift_undetected, 1)}s")

        row = db.query(MachineUtilization).filter(
            MachineUtilization.mc_id == mc_id,
            MachineUtilization.date == TARGET_DATE,
        ).first()

        if row is None:
            row = MachineUtilization(mc_id=mc_id, date=TARGET_DATE)
            db.add(row)
            print(f"  -> Creating new row for {mc_id} on {TARGET_DATE}")
        else:
            print(f"  -> Updating row id={row.id} for {mc_id} on {TARGET_DATE}")

        row.runtime = round(runtime, 2)
        row.downtime = round(downtime, 2)
        row.idle = 0.0
        row.total_available_time = round(total_available, 2)
        row.total_available_time_formatted = hms(total_available)
        row.utilization_percent = round(utilization, 2)
        row.undetected_time = round(shift_undetected, 2)
        row.offline_time = round(shift_undetected, 2)
        row.total_time = round(total_available, 2)

        # Build state dict for both utilization_state.json and utilization_state_repaired.json
        state_dict[today_str][mc_id] = {
            "runtime": round(runtime, 2),
            "downtime": round(downtime, 2),
            "offline": round(shift_undetected, 2),
            "undetected": 0.0,
            "undetected_time": round(shift_undetected, 2),
            "offline_time": round(shift_undetected, 2),
            "total_available_time": round(total_available, 2),
            "total_available_time_formatted": hms(total_available),
            "total_time": round(total_available, 2),
            "utilization_percent": round(utilization, 2)
        }

    # Write both utilization_state_repaired.json AND utilization_state.json
    with open("utilization_state_repaired.json", "w") as f:
        json.dump(state_dict, f, indent=2)
    with open("utilization_state.json", "w") as f:
        json.dump(state_dict, f, indent=2)

    db.commit()
    print(f"\n[REPAIR] Done. Database updated for {TARGET_DATE}.")
    print("[REPAIR] Updated 'utilization_state.json' and 'utilization_state_repaired.json'.")
    print("Next steps:")
    print("1. Copy utilization_state_repaired.json to the server and rename it to utilization_state.json")
    print("2. sudo systemctl start main-live.service")

if __name__ == "__main__":
    print(f"[REPAIR] Reconstructing utilization for {TARGET_DATE} from detection_events...")
    db = SessionLocal()
    try:
        repair(db)
    except Exception as e:
        print(f"[REPAIR ERROR] {e}")
        import traceback; traceback.print_exc()
    finally:
        db.close()
