"""Unit tests for configurable LLM and Embedding factories with local fallback."""

import os
from unittest.mock import patch

import pytest
from langchain_ollama import ChatOllama, OllamaEmbeddings
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from src.config import Settings, get_settings
from src.services.llm import get_embeddings, get_llm

_PROVIDER_ENV_PREFIXES = ("LLM_", "EMBEDDING_")
_PROVIDER_ENV_KEYS = ("OPENAI_API_KEY", "OPENROUTER_API_KEY")


@pytest.fixture(autouse=True)
def _default_provider_settings(tmp_path, monkeypatch):
    """These tests assert "no provider configured" fallback behavior, which must hold
    regardless of a real local .env (expected in dev, per the free-API setup docs) or
    ambient LLM_*/EMBEDDING_* vars in the shell. `get_settings()` is `@lru_cache`d and
    reads `env_file=".env"` relative to CWD, so both the raw env and the settings
    singleton need resetting — clearing os.environ alone would still leak through the
    cached Settings object.
    """
    for key in list(os.environ):
        if key.startswith(_PROVIDER_ENV_PREFIXES) or key in _PROVIDER_ENV_KEYS:
            monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()
    get_embeddings.cache_clear()
    yield
    get_settings.cache_clear()
    get_embeddings.cache_clear()


def test_get_llm_default_ollama():
    """Verify that get_llm defaults to ChatOllama with local settings."""
    llm = get_llm(provider="ollama")
    assert isinstance(llm, ChatOllama)
    assert llm.model == "llama3.1"


def test_get_llm_openai_without_key_falls_back():
    """Verify that selecting OpenAI without an API key falls back to local ChatOllama."""
    with patch.dict(os.environ, {"LLM_PROVIDER": "openai", "LLM_API_KEY": "", "OPENAI_API_KEY": ""}, clear=True):
        llm = get_llm(provider="openai", api_key="")
        assert isinstance(llm, ChatOllama)


def test_get_llm_openai_with_key():
    """Verify that selecting OpenAI with an API key instantiates ChatOpenAI."""
    llm = get_llm(provider="openai", model="gpt-4o-mini", api_key="sk-dummykey123")
    assert isinstance(llm, ChatOpenAI)
    assert llm.model_name == "gpt-4o-mini"


def test_get_llm_unknown_provider_falls_back():
    """Verify that an unknown provider safely falls back to local ChatOllama."""
    llm = get_llm(provider="unknown_provider_xyz")
    assert isinstance(llm, ChatOllama)


def test_get_embeddings_default_ollama():
    """Verify that get_embeddings defaults to local OllamaEmbeddings."""
    get_embeddings.cache_clear()
    embeddings = get_embeddings(provider="ollama")
    assert isinstance(embeddings, OllamaEmbeddings)
    assert embeddings.model == "bge-m3"


def test_get_embeddings_openai_without_key_falls_back():
    """Verify that selecting OpenAI embeddings without an API key falls back to local OllamaEmbeddings."""
    get_embeddings.cache_clear()
    with patch.dict(os.environ, {"EMBEDDING_PROVIDER": "openai", "EMBEDDING_API_KEY": "", "OPENAI_API_KEY": ""}, clear=True):
        embeddings = get_embeddings(provider="openai", api_key="")
        assert isinstance(embeddings, OllamaEmbeddings)


def test_get_embeddings_openai_with_key():
    """Verify that selecting OpenAI embeddings with an API key instantiates OpenAIEmbeddings."""
    get_embeddings.cache_clear()
    embeddings = get_embeddings(provider="openai", model="text-embedding-3-small", api_key="sk-dummykey123")
    assert isinstance(embeddings, OpenAIEmbeddings)
    assert embeddings.model == "text-embedding-3-small"


def test_get_embeddings_openrouter_bge_m3_with_key():
    """Verify that selecting OpenRouter with bge-m3 model configures OpenAIEmbeddings with baai/bge-m3."""
    get_embeddings.cache_clear()
    embeddings = get_embeddings(provider="openrouter", model="bge-m3", api_key="sk-or-dummy123")
    assert isinstance(embeddings, OpenAIEmbeddings)
    assert embeddings.model == "baai/bge-m3"
    assert "openrouter.ai" in str(embeddings.openai_api_base)


def test_get_embeddings_openrouter_without_key_falls_back():
    """Verify that selecting OpenRouter embedding without an API key falls back to local OllamaEmbeddings."""
    get_embeddings.cache_clear()
    with patch.dict(os.environ, {"EMBEDDING_PROVIDER": "openrouter", "EMBEDDING_API_KEY": "", "OPENROUTER_API_KEY": ""}, clear=True):
        embeddings = get_embeddings(provider="openrouter", api_key="")
        assert isinstance(embeddings, OllamaEmbeddings)
        assert embeddings.model == "bge-m3"
