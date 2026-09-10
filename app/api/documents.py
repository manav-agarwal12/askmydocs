from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.constants import PROGRESS_BY_STATUS, DocumentStatus
from app.core.database import get_db
from app.core.storage import save_pdf
from app.models import Chunk, Document, User
from app.schemas.document import DocumentOut, DocumentStatusOut, UploadAccepted, ChunkOut

router = APIRouter(prefix="/documents", tags=["documents"])


def _get_owned_document(document_id: int, db: Session, user: User) -> Document:
    """Fetch a document, but only if it belongs to this user."""
    document = db.get(Document, document_id)

    # 404 rather than 403 when it belongs to someone else — a 403 would
    # confirm to an attacker that this document id exists.
    if document is None or document.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )
    return document


@router.post(
    "/upload",
    response_model=UploadAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
def upload_document(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Accept a PDF and return a job id straight away.

    No parsing happens here — that is the worker's job. This handler must
    stay fast no matter how big or complex the PDF is.
    """
    stored_path, size_bytes = save_pdf(file, current_user.id)

    document = Document(
        user_id=current_user.id,
        filename=Path(file.filename).name,   # display name only, sanitised
        stored_path=stored_path,
        status=DocumentStatus.PENDING,
        attempts=0,
        doc_metadata={"size_bytes": size_bytes},
    )

    try:
        db.add(document)
        db.commit()
        db.refresh(document)
    except Exception:
        db.rollback()
        Path(stored_path).unlink(missing_ok=True)   # no orphan file on disk
        raise

    # Day 7-8: enqueue the Celery task here, e.g.
    #     process_document.delay(document.id)
    # The row already says "pending", so the worker has all it needs.

    return UploadAccepted(
        job_id=document.id,
        status=document.status,
        filename=document.filename,
    )


@router.get("/{document_id}/status", response_model=DocumentStatusOut)
def get_document_status(
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Cheap polling endpoint. The client hits this every couple of seconds."""
    document = _get_owned_document(document_id, db, current_user)

    chunks_indexed = (
        db.query(func.count(Chunk.id))
        .filter(Chunk.document_id == document.id)
        .scalar()
    )

    return DocumentStatusOut(
        job_id=document.id,
        status=document.status,
        progress=PROGRESS_BY_STATUS.get(document.status, 0),
        page_count=document.page_count,
        chunks_indexed=chunks_indexed or 0,
        attempts=document.attempts,
        error_message=document.error_message,
        processing_started_at=document.processing_started_at,
    )


@router.get("", response_model=list[DocumentOut])
def list_documents(
    limit: int = 20,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return (
        db.query(Document)
        .filter(Document.user_id == current_user.id)
        .order_by(Document.created_at.desc())
        .offset(offset)
        .limit(min(limit, 100))
        .all()
    )


@router.get("/{document_id}", response_model=DocumentOut)
def get_document(
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return _get_owned_document(document_id, db, current_user)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    document = _get_owned_document(document_id, db, current_user)
    stored_path = document.stored_path

    db.delete(document)   # chunks go too, via the cascade on the relationship
    db.commit()

    Path(stored_path).unlink(missing_ok=True)
    return None


@router.get("/{document_id}/chunks", response_model=list[ChunkOut])
def list_chunks(
    document_id: int,
    limit: int = 20,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Inspect the chunks produced for a document."""
    document = _get_owned_document(document_id, db, current_user)

    return (
        db.query(Chunk)
        .filter(Chunk.document_id == document.id)
        .order_by(Chunk.chunk_index)
        .offset(offset)
        .limit(min(limit, 100))
        .all()
    )