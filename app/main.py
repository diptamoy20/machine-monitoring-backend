import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.config import settings
from app.database.connection import engine, Base
from app.routes import machines
import os

# Configure basic logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create tables in PostgreSQL using SQLAlchemy Base
logger.info("Creating database tables if they do not exist...")
try:
    Base.metadata.create_all(bind=engine)
    logger.info("Tables created or verified successfully.")
except Exception as e:
    logger.error("Failed to create tables. Database might be unreachable.")
    logger.error(str(e))

app = FastAPI(
    title="Machine Monitoring Dashboard API",
    description="Backend API for monitoring machine statuses",
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

# Mount static files for images
# Ensure the directory exists before mounting
os.makedirs("app/static", exist_ok=True)
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Register routers
app.include_router(machines.router)

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
