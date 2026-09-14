import chromadb

from app.core.config import settings


class VectorStoreError(Exception):
    """Raised when there is a problem reading from or writing to ChromaDB."""


_client: chromadb.ClientAPI | None = None


def _get_client() -> chromadb.ClientAPI:
    """Create the persistent Chroma client once and reuse it."""
    global _client

    if _client is None:
        _client = chromadb.PersistentClient(path=settings.CHROMA_DIR)

    return _client


def collection_name_for_user(user_id: int) -> str:
    """Return a separate collection name for each user: user_1, user_2, etc."""
    return f"user_{user_id}"


def get_user_collection(user_id: int):
    """Get the user's collection, creating it if it does not already exist."""
    client = _get_client()

    return client.get_or_create_collection(
        name=collection_name_for_user(user_id),
        # Cosine similarity measures the angle between vectors.
        # It is well suited for text similarity searches.
        metadata={"hnsw:space": "cosine"},
    )


def replace_document_vectors(
    user_id: int,
    document_id: int,
    records: list[dict],
) -> int:
    """Remove all vectors for a document and insert the new ones.

    Expected records format:
        {"chunk_id": 12, "chunk_index": 0, "page_number": 1,
         "text": "...", "embedding": [0.1, ...]}
    """
    collection = get_user_collection(user_id)

    try:
        # Idempotency: remove existing vectors first.
        # This works similarly to deleting existing chunks in PostgreSQL.
        collection.delete(where={"document_id": document_id})

        if not records:
            return 0

        collection.upsert(
            ids=[str(record["chunk_id"]) for record in records],
            embeddings=[record["embedding"] for record in records],
            documents=[record["text"] for record in records],
            metadatas=[
                {
                    "document_id": document_id,
                    "chunk_id": record["chunk_id"],
                    "chunk_index": record["chunk_index"],
                    "page_no": record["page_number"] or 0,
                }
                for record in records
            ],
        )
    except Exception as exc:
        raise VectorStoreError(f"ChromaDB write failed: {exc}") from exc

    return len(records)


def delete_document_vectors(user_id: int, document_id: int) -> None:
    """Delete a document's vectors when the document is deleted."""
    try:
        collection = get_user_collection(user_id)
        collection.delete(where={"document_id": document_id})
    except Exception as exc:
        raise VectorStoreError(f"ChromaDB delete failed: {exc}") from exc