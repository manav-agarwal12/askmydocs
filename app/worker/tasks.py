import time

from sqlalchemy import func

from app.core.database import SessionLocal
from app.worker.celery_app import celery_app

from datetime import datetime, timezone
from app.core.constants import MAX_ATTEMPTS, DocumentStatus, STUCK_AFTER_MINUTES

from sqlalchemy.orm import Session

from app.models import Chunk, Document
from app.services.pdf import chunk_pages, extract_pages

from app.services.embeddings import embed_documents
from app.services.vectorstore import replace_document_vectors

from datetime import timedelta


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
    """Extract, chunk, embed, and store the vectors."""

    pages, total_pages = extract_pages(document.stored_path)
    chunks = chunk_pages(pages)

    db.query(Chunk).filter(Chunk.document_id == document.id).delete()

    chunk_rows = []
    for chunk in chunks:
        row = Chunk(
            document_id=document.id,
            chunk_index=chunk.chunk_index,
            text=chunk.text,
            page_number=chunk.page_number,
            chunk_metadata={"word_count": chunk.word_count},
        )
        db.add(row)
        chunk_rows.append(row)

    # flush = send the INSERT statements to PostgreSQL without committing.
    # This assigns IDs to the rows, which we need for ChromaDB vector IDs.
    db.flush()

    # This calls Gemini to generate embeddings.
    # It is the slowest step in this process.
    vectors = embed_documents([chunk.text for chunk in chunks])

    records = [
        {
            "chunk_id": row.id,
            "chunk_index": row.chunk_index,
            "page_number": row.page_number,
            "text": row.text,
            "embedding": vector,
        }
        for row, vector in zip(chunk_rows, vectors)
    ]

    vectors_stored = replace_document_vectors(
        user_id=document.user_id,
        document_id=document.id,
        records=records,
    )

    document.page_count = total_pages
    document.doc_metadata = {
        **(document.doc_metadata or {}),
        "pages_with_text": len(pages),
        "chunk_count": len(chunks),
        "vectors_stored": vectors_stored,
    }

    return {
        "pages": total_pages,
        "chunks": len(chunks),
        "vectors": vectors_stored,
    }

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


@celery_app.task(name="documents.recover_stuck")
def recover_stuck_documents() -> dict:
    """Make stuck and failed documents eligible for processing again.

    It does two things:
      1. Moves documents stuck in "processing" back to "pending"
      2. Moves failed documents back to "pending" if retry attempts remain
    """
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=STUCK_AFTER_MINUTES)

    db = SessionLocal()
    try:
        # --- 1. Stuck documents ---
        stuck = (
            db.query(Document)
            .filter(Document.status == DocumentStatus.PROCESSING)
            .filter(Document.processing_started_at < cutoff)
            .all()
        )

        requeued_stuck = 0
        for document in stuck:
            if document.attempts >= MAX_ATTEMPTS:
                document.status = DocumentStatus.FAILED
                document.error_message = (
                    f"Still not completed after {MAX_ATTEMPTS} attempts"
                )
            else:
                document.status = DocumentStatus.PENDING
                document.processing_started_at = None
                requeued_stuck += 1

        # --- 2. Failed documents with remaining retry attempts ---
        retryable = (
            db.query(Document)
            .filter(Document.status == DocumentStatus.FAILED)
            .filter(Document.attempts < MAX_ATTEMPTS)
            .all()
        )

        for document in retryable:
            document.status = DocumentStatus.PENDING
            document.processing_started_at = None

        db.commit()

        return {
            "requeued_stuck": requeued_stuck,
            "requeued_failed": len(retryable),
            "gave_up": len(stuck) - requeued_stuck,
        }
    finally:
        db.close()