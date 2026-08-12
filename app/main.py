import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from app.config import settings
from app.database.connection import engine, Base
from app.routes import machines, inference
import os

# Configure basic logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create tables in PostgreSQL using SQLAlchemy Base
logger.info("Creating database tables if they do not exist...")
try:
    Base.metadata.create_all(bind=engine)
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE machine_status ADD COLUMN IF NOT EXISTS video_url VARCHAR;"))
    logger.info("Tables created or verified successfully.")
except Exception as e:
    logger.error("Failed to create tables. Database might be unreachable.")
    logger.error(str(e))

app = FastAPI(
    title="Machine Monitoring Dashboard API",
    description="Backend API for monitoring machine statuses with YOLO inference",
    version="1.0.0"
)

# Configure CORS for frontend access
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files for images and videos
os.makedirs("app/static", exist_ok=True)
os.makedirs("app/static/videos", exist_ok=True)
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Register routers
app.include_router(machines.router)
app.include_router(inference.router)


@app.on_event("startup")
async def startup_event():
    """
    Load the YOLO model once at application startup.
    The model is held in memory and reused for all inference requests.
    If loading fails, the inference endpoints will return 503 but the
    machine monitoring API continues to work normally.
    """
    from app.ml.yolo import predictor
    try:
        predictor.load_model(
            model_path=settings.YOLO_MODEL_PATH,
            device=settings.YOLO_DEVICE,
        )
    except Exception as e:
        logger.error(f"YOLO model load failed at startup: {e}")
        logger.warning(
            "Machine status API will continue to work. "
            "Inference endpoints (POST /api/inference/*) will return 503 until the model is available."
        )


@app.get("/", summary="Root API endpoint")
def read_root():
    """
    Root endpoint verifying the API is up.
    """
    return {"message": "Machine Monitoring API is running"}


@app.get("/health", summary="Health check endpoint")
def health_check():
    """
    Health check for monitoring tools.
    """
    return {"status": "ok"}
