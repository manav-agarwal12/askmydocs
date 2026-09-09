from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.config import settings

# The engine manages a pool of connections to Postgres.
engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)

# A factory that hands out sessions. A session = one unit of work.
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Every model class will inherit from this.
Base = declarative_base()


def get_db():
    """FastAPI dependency: opens a session, closes it when the request ends."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()