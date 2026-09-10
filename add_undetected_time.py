"""
Migration: Add undetected_time column to detection_events and machine_utilization.

Run once:
    python add_undetected_time.py

Safe to re-run — uses IF NOT EXISTS so it won't error on already-migrated DBs.
"""
import sys
from sqlalchemy import text
from app.database.connection import engine

MIGRATIONS = [
    # detection_events
    """
    ALTER TABLE detection_events
    ADD COLUMN IF NOT EXISTS undetected_time FLOAT NOT NULL DEFAULT 0.0;
    """,
    # machine_utilization
    """
    ALTER TABLE machine_utilization
    ADD COLUMN IF NOT EXISTS undetected_time FLOAT NOT NULL DEFAULT 0.0;
    """,
]

def run():
    with engine.connect() as conn:
        for sql in MIGRATIONS:
            try:
                conn.execute(text(sql.strip()))
                conn.commit()
                print(f"OK: {sql.strip()[:60]}...")
            except Exception as e:
                print(f"ERROR: {e}", file=sys.stderr)
                sys.exit(1)
    print("\nMigration complete. Both tables now have 'undetected_time'.")

if __name__ == "__main__":
    run()
