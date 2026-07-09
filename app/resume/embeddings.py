"""Resume Embedding System — vector storage for semantic search, job
matching, and "similar resume/job" recommendations. Uses ChromaDB with its
built-in default embedding function (all-MiniLM-L6-v2) so no separate
embedding API call/key is required; keeps this system usable even with zero
AI provider keys configured.
"""

import logging
import uuid
from typing import Any

import chromadb

from app.core.config import settings
from app.resume.exceptions import EmbeddingGenerationFailedError

logger = logging.getLogger("app.resume.embeddings")

_client: Any = None


def get_chroma_client() -> Any:
    global _client
    if _client is None:
        _client = chromadb.HttpClient(host=settings.CHROMADB_HOST, port=settings.CHROMADB_PORT)
    return _client


def _get_collection():
    client = get_chroma_client()
    return client.get_or_create_collection(name=settings.CHROMADB_COLLECTION)


def upsert_resume_embedding(
    resume_id: uuid.UUID,
    user_id: uuid.UUID,
    text: str,
    metadata: dict,
) -> str:
    """Embeds and stores a resume's text. Returns the ChromaDB document id
    (persisted on Resume.embedding_id for later reference/deletion).
    """
    doc_id = str(resume_id)
    try:
        collection = _get_collection()
        collection.upsert(
            ids=[doc_id],
            documents=[text[:15000]],
            metadatas=[{"user_id": str(user_id), "resume_id": doc_id, **metadata}],
        )
        return doc_id
    except Exception as exc:  # noqa: BLE001
        logger.exception("embedding_upsert_failed", extra={"resume_id": doc_id})
        raise EmbeddingGenerationFailedError(str(exc)) from exc


def delete_resume_embedding(resume_id: uuid.UUID) -> None:
    try:
        collection = _get_collection()
        collection.delete(ids=[str(resume_id)])
    except Exception:  # noqa: BLE001
        logger.exception("embedding_delete_failed", extra={"resume_id": str(resume_id)})


def semantic_search(
    query_text: str,
    user_id: uuid.UUID,
    top_k: int = 10,
) -> list[dict]:
    """Semantic search scoped to a single user's resumes only (metadata
    filter enforces cross-user isolation at the vector-DB level too).
    """
    try:
        collection = _get_collection()
        results = collection.query(
            query_texts=[query_text[:5000]],
            n_results=top_k,
            where={"user_id": str(user_id)},
        )
        matches = []
        ids = results.get("ids", [[]])[0]
        distances = results.get("distances", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        for doc_id, distance, meta in zip(ids, distances, metadatas):
            matches.append({
                "resume_id": doc_id,
                "similarity_score": round(1 - distance, 4) if distance is not None else None,
                "metadata": meta,
            })
        return matches
    except Exception as exc:  # noqa: BLE001
        logger.exception("semantic_search_failed")
        raise EmbeddingGenerationFailedError(str(exc)) from exc
