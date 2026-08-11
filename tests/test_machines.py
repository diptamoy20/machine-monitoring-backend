from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

# Use test overrides or an isolated test database in a real scenario
# Here we just mock simple endpoints that don't depend on the db

def test_read_root():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"message": "Machine Monitoring API is running"}

def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

# The following tests hit the actual database, so we expect the seed script to have been run
def test_get_all_machines():
    response = client.get("/api/machines")
    assert response.status_code == 200
    assert isinstance(response.json(), list)

def test_create_invalid_status():
    response = client.post("/api/machines", json={
        "mc_id": "MC-TEST",
        "name": "Test Machine",
        "status": "INVALID_STATUS"
    })
    assert response.status_code == 422 # Unprocessable Entity

def test_update_machine_not_found():
    response = client.put("/api/machines/MC-UNKNOWN", json={
        "status": "standby"
    })
    assert response.status_code == 404
