"""
Migration + Seed script for machine_utilization table.

Does the following in order:
1. Drops the unique constraint uq_mc_id_date (if it exists)
2. Alters the date column from TIMESTAMPTZ -> DATE (if still TIMESTAMPTZ)
3. Normalises any existing rows that still have timestamps as their date
4. Clears ALL rows so we start clean with the seed data below
5. Inserts realistic dummy data for 2026-09-04, 2026-09-07, and 2026-09-08
"""

import os, sys
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from app.database.connection import engine
from sqlalchemy import text

# ── helpers ────────────────────────────────────────────────────────────────────

def fmt(seconds: float) -> str:
    t = int(round(seconds))
    h, rem = divmod(t, 3600)
    m, s   = divmod(rem, 60)
    return f"{h}h {m}m {s}s"

def util_pct(runtime: float, total: float) -> float:
    return round((runtime / total * 100) if total > 0 else 0.0, 2)

# ── seed data ──────────────────────────────────────────────────────────────────
# Values are stored as SECONDS in the DB (matching the detection pipeline output)

SEED = [
    # ── 2026-09-04 (real data from log file) ───────────────────────────────────
    # runtime, downtime, idle  (all in seconds)
    ("MC-001", "2026-09-04", 26586.0, 299.0,  14508.0),
    ("MC-002", "2026-09-04", 4025.0,  13882.0, 23486.0),
    ("MC-003", "2026-09-04", 26032.0, 209.0,  15134.0),
    ("MC-004", "2026-09-04", 13277.0, 4.0,    17968.0),
    ("MC-005", "2026-09-04", 2599.0,  238.0,  25182.0),
    ("MC-006", "2026-09-04", 727.0,   2689.0, 24602.0),

    # ── 2026-09-07 (moderate production day) ───────────────────────────────────
    ("MC-001", "2026-09-07", 35000.0, 600.0,  10000.0),
    ("MC-002", "2026-09-07", 8000.0,  12600.0, 25000.0),
    ("MC-003", "2026-09-07", 34000.0, 600.0,  11000.0),
    ("MC-004", "2026-09-07", 12000.0, 100.0,  20000.0),
    ("MC-005", "2026-09-07", 2000.0,  200.0,  26000.0),
    ("MC-006", "2026-09-07", 600.0,   3000.0, 21000.0),

    # ── 2026-09-08 (today – partial day up to ~13:30 IST) ──────────────────────
    ("MC-001", "2026-09-08", 48347.0, 300.0,  14527.0),
    ("MC-002", "2026-09-08", 11021.0, 14765.0, 37383.0),
    ("MC-003", "2026-09-08", 47522.0, 222.0,  15413.0),
    ("MC-004", "2026-09-08", 13278.0, 5.0,    39746.0),
    ("MC-005", "2026-09-08", 2599.0,  238.0,  46961.0),
    ("MC-006", "2026-09-08", 726.0,   2690.0, 46382.0),
]

# ── run migration ──────────────────────────────────────────────────────────────

with engine.begin() as conn:
    print("Step 1: Drop unique constraint if it exists...")
    conn.execute(text("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'uq_mc_id_date'
            ) THEN
                ALTER TABLE machine_utilization DROP CONSTRAINT uq_mc_id_date;
                RAISE NOTICE 'Dropped uq_mc_id_date';
            ELSE
                RAISE NOTICE 'uq_mc_id_date did not exist, skipping';
            END IF;
        END $$;
    """))

    print("Step 2: Change date column to DATE type if it is still TIMESTAMPTZ...")
    conn.execute(text("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'machine_utilization'
                  AND column_name = 'date'
                  AND data_type IN ('timestamp with time zone', 'timestamp without time zone')
            ) THEN
                ALTER TABLE machine_utilization ALTER COLUMN date TYPE DATE USING date::DATE;
                RAISE NOTICE 'Changed date column to DATE';
            ELSE
                RAISE NOTICE 'date column already DATE, skipping';
            END IF;
        END $$;
    """))

    print("Step 3: Clear all existing rows...")
    conn.execute(text("DELETE FROM machine_utilization;"))

    print("Step 4: Insert seed data...")
    insert_sql = text("""
        INSERT INTO machine_utilization
            (mc_id, date, runtime, downtime, idle,
             total_available_time, total_available_time_formatted,
             utilization_percent, updated_at)
        VALUES
            (:mc_id, :date, :runtime, :downtime, :idle,
             :total, :total_fmt,
             :util_pct, NOW())
    """)

    for mc_id, date_str, runtime, downtime, idle in SEED:
        total = runtime + downtime + idle
        conn.execute(insert_sql, {
            "mc_id":    mc_id,
            "date":     date_str,
            "runtime":  runtime,
            "downtime": downtime,
            "idle":     idle,
            "total":    total,
            "total_fmt": fmt(total),
            "util_pct": util_pct(runtime, total),
        })
        print(f"  Inserted {mc_id} @ {date_str}  util={util_pct(runtime, total)}%")

print("\nAll done. Verifying rows in DB:")
with engine.connect() as conn:
    rows = conn.execute(text(
        "SELECT mc_id, date, runtime, downtime, idle, utilization_percent "
        "FROM machine_utilization ORDER BY date, mc_id"
    ))
    for r in rows:
        print(f"  {r.mc_id}  {r.date}  rt={r.runtime}  dt={r.downtime}  idle={r.idle}  util={r.utilization_percent}%")
