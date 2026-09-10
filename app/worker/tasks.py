import time

from sqlalchemy import func

from app.core.database import SessionLocal
from app.models import Document
from app.worker.celery_app import celery_app

from datetime import datetime, timezone
from app.core.constants import MAX_ATTEMPTS, DocumentStatus


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


def _claim_one_pending() -> int | None:
    """Lock one pending document, flip it to processing, return its id.

    Kept deliberately tiny: the row lock is held only for the few
    milliseconds this transaction takes.
    """
    db = SessionLocal()
    try:
        document = (
            db.query(Document)
            .filter(Document.status == DocumentStatus.PENDING)
            .order_by(Document.created_at)          # oldest first, fair queue
            .with_for_update(skip_locked=True)      # see note below
            .first()
        )

        if document is None:
            return None

        document.status = DocumentStatus.PROCESSING
        document.processing_started_at = datetime.now(timezone.utc)
        document.attempts += 1
        document.error_message = None               # clear any previous failure
        db.commit()

        return document.id
    finally:
        db.close()


def _finish(document_id: int) -> dict:
    """Do the work, then record the outcome. No real work yet."""
    db = SessionLocal()
    try:
        document = db.get(Document, document_id)
        if document is None:
            return {"document_id": document_id, "status": "vanished"}

        try:
            # ---- Day 10-11: real work goes here ----
            # open the PDF with PyMuPDF, extract text, write chunks
            time.sleep(3)          # pretend it took a moment
            document.page_count = 0
            # ----------------------------------------

            document.status = DocumentStatus.COMPLETED
            document.error_message = None
        except Exception as exc:
            document.status = DocumentStatus.FAILED
            document.error_message = f"{type(exc).__name__}: {exc}"[:1000]

        db.commit()
        return {
            "document_id": document.id,
            "status": document.status,
            "attempts": document.attempts,
        }
    finally:
        db.close()


@celery_app.task(name="documents.claim_next")
def claim_next_document() -> dict:
    """Runs every 30 seconds via Celery Beat. Processes at most one document."""
    document_id = _claim_one_pending()

    if document_id is None:
        return {"claimed": None, "reason": "no pending documents"}

    return _finish(document_id)