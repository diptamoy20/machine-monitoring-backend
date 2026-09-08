import os
import sys

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from app.database.connection import engine
from sqlalchemy import text

def migrate():
    with engine.begin() as conn:
        try:
            print("Running migration for machine_utilization...")
            # Drop the primary key constraint on mc_id
            conn.execute(text("ALTER TABLE machine_utilization DROP CONSTRAINT machine_utilization_pkey;"))
            print("Dropped primary key constraint.")
            
            # Add id column and make it primary key
            conn.execute(text("ALTER TABLE machine_utilization ADD COLUMN id SERIAL PRIMARY KEY;"))
            print("Added id column as primary key.")
            
            # Add date column and populate it with created_at date or today's date if not available
            # We can use updated_at cast to date
            conn.execute(text("ALTER TABLE machine_utilization ADD COLUMN date TIMESTAMP WITH TIME ZONE;"))
            conn.execute(text("UPDATE machine_utilization SET date = updated_at;"))
            conn.execute(text("ALTER TABLE machine_utilization ALTER COLUMN date SET NOT NULL;"))
            print("Added date column.")
            
            # Add unique constraint on (mc_id, date)
            conn.execute(text("ALTER TABLE machine_utilization ADD CONSTRAINT uq_mc_id_date UNIQUE (mc_id, date);"))
            print("Added unique constraint on mc_id and date.")
            
            print("Migration completed successfully.")
        except Exception as e:
            print(f"Error during migration: {e}")
            raise

if __name__ == "__main__":
    migrate()
