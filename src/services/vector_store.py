from langchain_ollama import OllamaEmbeddings
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient

from src.config import get_settings


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

    # Initialize Qdrant client
    client = QdrantClient(
        url=settings.qdrant_url,
        api_key=settings.qdrant_api_key if settings.qdrant_api_key else None
    )
    
    return QdrantVectorStore(
        client=client,
        collection_name=collection_name,
        embedding=embeddings,
    )
