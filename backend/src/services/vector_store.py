from functools import lru_cache

from langchain_ollama import OllamaEmbeddings
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient

from src.config import get_settings


@lru_cache(maxsize=1)
def get_qdrant_client() -> QdrantClient:
    """
    Process-scoped QdrantClient singleton. `get_settings()` is itself
    `lru_cache`d, so a settings change (e.g. a new API key) only takes effect
    after a process restart — this is not hot-reloadable by design.
    """
    settings = get_settings()
    return QdrantClient(
        url=settings.qdrant_url,
        api_key=settings.qdrant_api_key if settings.qdrant_api_key else None,
        # Default client timeout is too tight for a remote cluster's
        # round-trip (a local container never hit this; Qdrant Cloud did).
        timeout=60,
    )


def get_vector_store(collection_name: str) -> QdrantVectorStore:
    """
    Initializes and returns a QdrantVectorStore instance.
    """
    settings = get_settings()

    # Initialize Ollama embeddings for BGE-M3
    embeddings = OllamaEmbeddings(
        model="bge-m3",
        base_url=settings.ollama_url
    )

    return QdrantVectorStore(
        client=get_qdrant_client(),
        collection_name=collection_name,
        embedding=embeddings,
    )
