from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from app.config import settings

# Engine configuration for PostgreSQL
# pool_size + max_overflow capped per worker process to avoid exhausting
# the database's max_connections limit when running with multiple uvicorn
# workers. pool_pre_ping checks connections are alive before reuse (avoids
# "server closed the connection unexpectedly" after idle periods or network
# blips). pool_recycle proactively closes/reopens connections older than
# 30 minutes to avoid stale connections lingering.
engine = create_engine(
    settings.database_url,
    echo=False,
    future=True,
    pool_size=3,
    max_overflow=2,
    pool_pre_ping=True,
    pool_recycle=1800,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
