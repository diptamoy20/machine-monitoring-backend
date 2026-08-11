# Machine Monitoring Dashboard Backend (FastAPI POC)
## server upload path 
/var/www/dev.beas.in/public_html/Machine_monitor

## 1. Project Purpose
This is a Proof of Concept (POC) backend for Anil Balaji Steel Pvt. Ltd. Machine Monitoring Dashboard. It provides a RESTful API built with FastAPI, using PostgreSQL for database storage via SQLAlchemy, to monitor the running status (running, standby, stop) of 6 industrial machines.

## 2. Architecture
The architecture is designed to be clean, modular, and maintainable, serving as a stable intermediate layer between the PostgreSQL database and the Frontend. The separation of concerns ensures that the AI model can later be integrated to update machine states without breaking the frontend's API contract.

- **PostgreSQL**: Stores the current state of machines.
- **FastAPI**: Provides API endpoints.
- **Services layer**: Contains database interaction logic and business rules.
- **Routes layer**: Handles API requests and responses.

## 3. Folder Structure
```
machine-monitoring-backend/
│
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── config.py
│   │
│   ├── database/
│   │   ├── __init__.py
│   │   ├── connection.py
│   │   └── models.py
│   │
│   ├── schemas/
│   │   ├── __init__.py
│   │   └── machine.py
│   │
│   ├── routes/
│   │   ├── __init__.py
│   │   └── machines.py
│   │
│   ├── services/
│   │   ├── __init__.py
│   │   └── machine_service.py
│   │
│   └── static/
│       └── images/
│
├── scripts/
│   ├── __init__.py
│   └── seed_machines.py
│
├── tests/
│   ├── __init__.py
│   └── test_machines.py
│
├── .env
├── .env.example
├── .gitignore
├── requirements.txt
├── README.md
└── run.py
```

## 4. PostgreSQL Configuration
The PostgreSQL server must already exist at `192.168.1.30:5433`.
The project uses the **existing database** `machine_monitoring` and the **existing default schema** `public`.

```
PostgreSQL (192.168.1.30:5433)
    |
    └── machine_monitoring
            |
            └── public
                    |
                    └── machine_status (Automatically Created)
```

## 5. Environment Variables
Copy the example environment file:
```bash
cp .env.example .env
```
Ensure you update `.env` with your actual `DB_PASSWORD`. Never commit this file to version control.

## 6. Virtual Environment Setup (Windows)
Create and activate a virtual environment:
```bash
python -m venv venv
venv\Scripts\activate
```

## 7. Dependency Installation
Install required packages:
```bash
pip install -r requirements.txt
```

## 8. Database Connection
The application connects to PostgreSQL using `psycopg` and `SQLAlchemy`. The connection URL is safely constructed from environment variables in `app/config.py` to handle any special characters in the password.

## 9. How the Table gets Created Automatically
When the application starts, it runs `Base.metadata.create_all(bind=engine)` in `app/main.py`. This instructs SQLAlchemy to check if the `machine_status` table exists in the database. If it does not exist, it will be automatically created using the schema defined in `app/database/models.py`.

*Note: For production environments, it is recommended to introduce Alembic migrations instead of `create_all()`.*

## 10. How to Seed Six Machines
Run the provided seed script to populate the database with the initial 6 machines. This script is safe to run multiple times. If a machine already exists, it will update its information.
```bash
python scripts/seed_machines.py
```

## 11. How to Run FastAPI
You can start the backend using either of the following commands:
```bash
python run.py
```
OR
```bash
uvicorn app.main:app --reload
```

## 12. API Documentation
Once the server is running, FastAPI automatically provides Swagger UI documentation.
Visit: [http://localhost:8000/docs](http://localhost:8000/docs)

## 13. API Endpoints
- `GET /` - Root health endpoint.
- `GET /health` - Service health check.
- `GET /api/machines` - Retrieve all monitored machines.
- `GET /api/machines/{mc_id}` - Retrieve a specific machine by ID.
- `POST /api/machines` - Create a new machine.
- `PUT /api/machines/{mc_id}` - Update a machine's status or metadata.
- `PATCH /api/machines/{mc_id}` - Partially update a machine.

*PUT vs PATCH:* PUT is used for completely replacing a resource or updating all of its significant fields. PATCH is used for partial updates (e.g., updating only the status). In this POC, both map to the same robust update logic.

## 14. Example API Requests/Responses

**Request (GET /api/machines):**
```bash
curl -X 'GET' 'http://localhost:8000/api/machines' -H 'accept: application/json'
```

**Response:**
```json
[
  {
    "name": "Machine 01",
    "image_url": "/static/images/machine-01.jpg",
    "status": "running",
    "id": 1,
    "mc_id": "MC-001",
    "created_at": "2026-08-11T10:30:00+00:00",
    "updated_at": "2026-08-11T10:30:00+00:00"
  },
  ...
]
```

**Request (PUT /api/machines/MC-001):**
```bash
curl -X 'PUT' 'http://localhost:8000/api/machines/MC-001' \
  -H 'accept: application/json' \
  -H 'Content-Type: application/json' \
  -d '{"status": "standby"}'
```

**Response:**
```json
{
  "name": "Machine 01",
  "image_url": "/static/images/machine-01.jpg",
  "status": "standby",
  ...
}
```

## 15. How the Frontend Connects
The React frontend can communicate with the backend during development. Update the `FRONTEND_URL` environment variable if your frontend runs on a different port than `http://localhost:5173`. 
The frontend just needs to call `GET /api/machines` to retrieve the machine states and update the UI accordingly (e.g. mapping `running` -> green, `standby` -> yellow, `stop` -> red).

## 16. Static Image Handling
Images are stored locally inside `app/static/images/`. The paths saved in the database point to the `/static/...` route, which FastAPI exposes. Note that actual machine image files must be manually placed inside this folder (e.g. `app/static/images/machine-01.jpg`), as the database only stores the URLs.

## 17. Future AI Integration Architecture
This POC sets the stage for future AI model integration. 
The AI model will NOT connect directly to PostgreSQL. Instead, the workflow will be:
```
AI Model  →  FastAPI Endpoint (e.g. PUT/PATCH)  →  Machine Service Validation  →  PostgreSQL Database
```
The AI model can call `PUT /api/machines/{mc_id}` with updated statuses. This allows the frontend API contract (`GET /api/machines`) to remain completely stable and unaware of how the data is being updated.

## 18. Information Required From AI/ML Team Before Integration
Before integrating the AI model, the following information must be confirmed:
1. Exact model output format (JSON structure).
2. Machine ID format mapping.
3. Exact status values produced.
4. Prediction frequency (e.g., once a second, once a minute).
5. Whether predictions are real-time streams or batch updates.
6. How the image is delivered (URL, base64, object storage, etc.).
7. Image format (jpeg, png).
8. Image storage location.
9. Confidence score availability (will we need to store it?).
10. Model version information.
11. What happens when the prediction is unavailable/fails?
12. Expected response time of predictions.
13. Whether historical predictions need to be stored in a time-series table.
14. Whether the model runs locally or remotely.
15. How FastAPI should communicate with the model (Push vs Pull).
16. Whether the model exposes an HTTP API.
17. Whether the model runs as a Python package/process.
18. Error/failure fallback behavior.

## 19. Production Recommendations
- Switch to Alembic for database migrations instead of automatic `create_all()`.
- Use a dedicated database user (e.g. `machine_monitoring_user`) instead of the default `postgres` superuser.
- Implement more extensive exception logging (e.g. Sentry) and metric gathering.
- Serve static files (images) through a CDN or NGINX instead of FastAPI StaticFiles.
