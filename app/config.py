import os
from dotenv import load_dotenv
from sqlalchemy.engine import URL
from typing import Optional

load_dotenv()

class Settings:
    # --- Database ---
    DB_HOST = os.getenv("DB_HOST", "192.168.1.30")
    DB_PORT = os.getenv("DB_PORT", "5433")
    DB_USER = os.getenv("DB_USER", "postgres")
    DB_PASSWORD = os.getenv("DB_PASSWORD", "postgres")
    DB_NAME = os.getenv("DB_NAME", "machine_monitoring")
    FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")

    # --- YOLO Inference ---
    # Path to trained model weights (.pt file), relative to project root
    YOLO_MODEL_PATH: str = os.getenv("YOLO_MODEL_PATH", "app/ml/yolo/weights/best.pt")

    # Directory containing inference videos
    YOLO_VIDEO_DIR: str = os.getenv("YOLO_VIDEO_DIR", "app/static/videos")

    # Inference device: 'cpu' or '0' (first CUDA GPU)
    YOLO_DEVICE: str = os.getenv("YOLO_DEVICE", "cpu")

    # Minimum confidence (0.0–1.0) to accept a frame prediction
    YOLO_CONFIDENCE_THRESHOLD: float = float(os.getenv("YOLO_CONFIDENCE_THRESHOLD", "0.5"))

    # Number of recent frames used for majority-vote smoothing
    YOLO_SMOOTHING_WINDOW: int = int(os.getenv("YOLO_SMOOTHING_WINDOW", "10"))

    # Max frames to sample per video (None = all frames). Set lower for speed on POC.
    _max_frames_env = os.getenv("YOLO_MAX_FRAMES", "")
    YOLO_MAX_FRAMES: Optional[int] = int(_max_frames_env) if _max_frames_env.strip() else None

    @property
    def database_url(self) -> str:
        # Construct the database URL safely without manual string concatenation
        return URL.create(
            drivername="postgresql+psycopg",
            username=self.DB_USER,
            password=self.DB_PASSWORD,
            host=self.DB_HOST,
            port=self.DB_PORT,
            database=self.DB_NAME
        ).render_as_string(hide_password=False)

settings = Settings()
