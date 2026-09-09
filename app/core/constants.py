class DocumentStatus:
    """The only valid values for documents.status."""

    PENDING = "pending"        # uploaded, waiting for a worker
    PROCESSING = "processing"  # a worker picked it up
    COMPLETED = "completed"    # text extracted and chunked
    FAILED = "failed"          # gave up after retries


# Rough progress percentage shown to the client, keyed by status.
PROGRESS_BY_STATUS = {
    DocumentStatus.PENDING: 0,
    DocumentStatus.PROCESSING: 50,
    DocumentStatus.COMPLETED: 100,
    DocumentStatus.FAILED: 0,
}