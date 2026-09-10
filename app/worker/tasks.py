import time

from sqlalchemy import func

from app.core.database import SessionLocal
from app.worker.celery_app import celery_app

from datetime import datetime, timezone
from app.core.constants import MAX_ATTEMPTS, DocumentStatus

from sqlalchemy.orm import Session

from app.models import Chunk, Document
from app.services.pdf import chunk_pages, extract_pages


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


def _process(document: Document, db: Session) -> dict:
    """The real work. Raises on any problem; the caller records the failure."""
    pages, total_pages = extract_pages(document.stored_path)
    chunks = chunk_pages(pages)

    # Idempotency: a retry must not double-insert. Wipe anything a
    # previous attempt left behind before writing fresh chunks.
    db.query(Chunk).filter(Chunk.document_id == document.id).delete()

    for chunk in chunks:
        db.add(
            Chunk(
                document_id=document.id,
                chunk_index=chunk.chunk_index,
                text=chunk.text,
                page_number=chunk.page_number,
                chunk_metadata={"word_count": chunk.word_count},
            )
        )

    document.page_count = total_pages

    # Reassign the whole dict. Mutating a JSONB dict in place does not
    # mark the row dirty, so SQLAlchemy would never save the change.
    document.doc_metadata = {
        **(document.doc_metadata or {}),
        "pages_with_text": len(pages),
        "chunk_count": len(chunks),
    }

    return {"pages": total_pages, "chunks": len(chunks)}


def _finish(document_id: int) -> dict:
    """Run the work and record the outcome as completed or failed."""
    db = SessionLocal()
    try:
        document = db.get(Document, document_id)
        if document is None:
            return {"document_id": document_id, "status": "vanished"}

        try:
            stats = _process(document, db)
            document.status = DocumentStatus.COMPLETED
            document.error_message = None
        except Exception as exc:
            # Roll back first: the session may be in a broken transaction,
            # and any half-inserted chunks must go. After a rollback the
            # object is expired, so re-fetch it before writing the failure.
            db.rollback()
            document = db.get(Document, document_id)
            document.status = DocumentStatus.FAILED
            document.error_message = f"{type(exc).__name__}: {exc}"[:1000]
            stats = {}

        db.commit()
        return {
            "document_id": document.id,
            "status": document.status,
            "attempts": document.attempts,
            **stats,
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