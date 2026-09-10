from datetime import datetime

from pydantic import BaseModel, ConfigDict


class UploadAccepted(BaseModel):
    """Returned immediately from POST /documents/upload."""
    job_id: int
    status: str
    filename: str
    message: str = "Upload accepted. Poll /documents/{job_id}/status for progress."


class DocumentStatusOut(BaseModel):
    """Returned from GET /documents/{id}/status."""
    job_id: int
    status: str
    progress: int
    page_count: int | None
    chunks_indexed: int
    attempts: int
    error_message: str | None
    processing_started_at: datetime | None


class DocumentOut(BaseModel):
    """Full document record, for list and detail routes."""
    id: int
    filename: str
    status: str
    page_count: int | None
    error_message: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class ChunkOut(BaseModel):
    id: int
    chunk_index: int
    page_number: int | None
    text: str

    model_config = ConfigDict(from_attributes=True)