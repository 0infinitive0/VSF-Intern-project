"""RAGAS judge LLM + embeddings, wired through the app's own model factory
so the eval harness and the app agree on how a provider is configured.
"""

from pathlib import Path

from ragas.cache import DiskCacheBackend
from ragas.embeddings import LangchainEmbeddingsWrapper
from ragas.llms import LangchainLLMWrapper

from src.services.llm import get_embeddings, get_llm

_CACHE = DiskCacheBackend(cache_dir=str(Path(__file__).resolve().parent.parent / ".ragas_cache"))


def build_judge():
    """gpt-4o-mini at temperature 0 - deterministic enough to compare runs."""
    return LangchainLLMWrapper(
        get_llm(provider="openai", model="gpt-4o-mini", temperature=0.0),
        cache=_CACHE,
    )


def build_judge_embeddings():
    """The app's configured embedding, for the metrics that need one.

    Layer 2 no longer does: `ResponseRelevancy` was dropped on 2026-08-20 and
    Faithfulness is text-only. `smoke_check.py` still builds this, so it stays.
    """
    return LangchainEmbeddingsWrapper(get_embeddings(), cache=_CACHE)
