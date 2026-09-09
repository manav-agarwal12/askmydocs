import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile, status

from app.core.config import settings

MAX_FILE_SIZE = 20 * 1024 * 1024   # 20 MB
CHUNK_SIZE = 1024 * 1024           # read 1 MB at a time
PDF_MAGIC = b"%PDF-"               # every real PDF starts with these bytes


def _upload_root() -> Path:
    """Absolute path to the uploads folder, created if missing."""
    root = Path(settings.UPLOAD_DIR).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def save_pdf(file: UploadFile, user_id: int) -> tuple[str, int]:
    """Validate and store an uploaded PDF. Returns (stored_path, size_bytes)."""
    original_name = file.filename or ""
    if not original_name.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only .pdf files are allowed",
        )

    user_dir = _upload_root() / f"user_{user_id}"
    user_dir.mkdir(parents=True, exist_ok=True)

    # Never reuse the client's filename on disk. It can contain "../.." and
    # overwrite files elsewhere, or collide with another user's upload.
    destination = user_dir / f"{uuid.uuid4().hex}.pdf"

    size = 0
    is_first_chunk = True

    try:
        with destination.open("wb") as out:
            while chunk := file.file.read(CHUNK_SIZE):
                if is_first_chunk:
                    if not chunk.startswith(PDF_MAGIC):
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail="File is not a valid PDF",
                        )
                    is_first_chunk = False

                size += len(chunk)
                if size > MAX_FILE_SIZE:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail="File too large (max 20 MB)",
                    )
                out.write(chunk)

        if size == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Uploaded file is empty",
            )
    except Exception:
        destination.unlink(missing_ok=True)  # don't leave half-written junk
        raise
    finally:
        file.file.close()

    return str(destination), size