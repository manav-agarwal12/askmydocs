import time

from sqlalchemy import func

from app.core.database import SessionLocal
from app.models import Document
from app.worker.celery_app import celery_app


@celery_app.task(name="debug.ping")
def ping() -> str:
    """Simplest possible task. If this works, the plumbing works."""
    return "pong"


@celery_app.task(name="debug.slow_add")
def slow_add(a: int, b: int, seconds: int = 5) -> int:
    """Deliberately slow, to prove the API never waits for the worker."""
    time.sleep(seconds)
    return a + b


@celery_app.task(name="debug.count_documents")
def count_documents() -> dict:
    """Proves the worker can reach Postgres on its own."""
    # No FastAPI request here, so no get_db dependency. The worker opens
    # and closes its own session, every single time.
    db = SessionLocal()
    try:
        total = db.query(func.count(Document.id)).scalar() or 0
        pending = (
            db.query(func.count(Document.id))
            .filter(Document.status == "pending")
            .scalar()
            or 0
        )
        return {"total": total, "pending": pending}
    finally:
        db.close()


@celery_app.task(name="debug.boom")
def boom() -> None:
    """Fails on purpose, so you can see what a FAILURE looks like."""
    raise ValueError("This task fails on purpose")