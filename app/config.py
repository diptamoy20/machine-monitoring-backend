import os
from dotenv import load_dotenv
from sqlalchemy.engine import URL

load_dotenv()

class Settings:
    DB_HOST = os.getenv("DB_HOST", "192.168.1.30")
    DB_PORT = os.getenv("DB_PORT", "5433")
    DB_USER = os.getenv("DB_USER", "postgres")
    DB_PASSWORD = os.getenv("DB_PASSWORD", "postgres")
    DB_NAME = os.getenv("DB_NAME", "machine_monitoring")
    FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")

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
