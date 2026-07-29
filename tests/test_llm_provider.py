"""Unit tests for configurable LLM and Embedding factories with local fallback."""

import os
from unittest.mock import patch

from langchain_ollama import ChatOllama, OllamaEmbeddings
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from src.config import Settings
from src.services.llm import get_embeddings, get_llm


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
