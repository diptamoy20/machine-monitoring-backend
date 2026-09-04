"""One-off cleanup: removes the MC-TEST-999 row created during API testing."""
from app.database.connection import SessionLocal
from app.database.models import MachineStatus

db = SessionLocal()
try:
    row = db.query(MachineStatus).filter(MachineStatus.mc_id == "MC-TEST-999").first()
    if row:
        db.delete(row)
        db.commit()
        print("Deleted MC-TEST-999.")
    else:
        print("MC-TEST-999 not found - already removed.")
finally:
    db.close()
