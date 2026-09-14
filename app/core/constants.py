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


# How many times we retry a document before giving up.
MAX_ATTEMPTS  = 3  # how many times a worker will retry a failed document

# Chunking. English averages ~0.75 words per token, so 375 words is
# roughly 500 tokens and 38 words is roughly 50 tokens of overlap.
CHUNK_SIZE_WORDS = 375
CHUNK_OVERLAP_WORDS = 38

# --- Embeddings ---
# gemini-embedding-001 returns 3072 numbers by default.
# We truncate it to 768 dimensions, which has only about a 0.3% impact on quality
# while reducing storage requirements by approximately 4x.
EMBEDDING_MODEL = "gemini-embedding-001"
EMBEDDING_DIMENSIONS = 768

# When storing a document chunk and searching for a user question,
# we need to tell Gemini what task the embedding is being used for.
# These two task types are different — explained below.
TASK_TYPE_DOCUMENT = "RETRIEVAL_DOCUMENT"
TASK_TYPE_QUERY = "RETRIEVAL_QUERY"

# How long to wait before considering a document in "processing" status as stuck.
STUCK_AFTER_MINUTES = 10