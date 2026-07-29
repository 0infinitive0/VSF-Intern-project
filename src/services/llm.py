"""Unified model factory for Chat LLMs and Embeddings with automatic fallback to local models."""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Any

from langchain_core.embeddings import Embeddings
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_ollama import ChatOllama, OllamaEmbeddings
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from src.config import get_settings

logger = logging.getLogger(__name__)


def _get_local_llm(
    model: str | None = None,
    temperature: float | None = None,
    base_url: str | None = None,
) -> BaseChatModel:
    """Return local ChatOllama model instance."""
    settings = get_settings()
    target_model = model or getattr(settings, "llm_model", "llama3.1") or "llama3.1"
    target_url = base_url or getattr(settings, "ollama_url", "http://localhost:11434")
    target_temp = temperature if temperature is not None else getattr(settings, "llm_temperature", 0.3)
    return ChatOllama(model=target_model, base_url=target_url, temperature=target_temp)


def _get_local_embeddings(
    model: str | None = None,
    base_url: str | None = None,
) -> Embeddings:
    """Return local OllamaEmbeddings model instance."""
    settings = get_settings()
    target_model = model or getattr(settings, "embedding_model", "bge-m3") or "bge-m3"
    target_url = base_url or getattr(settings, "ollama_url", "http://localhost:11434")
    return OllamaEmbeddings(model=target_model, base_url=target_url)


def get_llm(
    provider: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    temperature: float | None = None,
    base_url: str | None = None,
) -> BaseChatModel:
    """Return configured Chat LLM instance with local Ollama fallback.

    Args:
        provider: Provider name ("ollama", "openai", "google", "gemini", "anthropic").
        model: Model name string (e.g. "llama3.1", "gpt-4o-mini").
        api_key: API key for remote providers.
        temperature: Sampling temperature.
        base_url: Custom API endpoint base URL.
    """
    settings = get_settings()

    target_provider = (
        provider
        or os.environ.get("LLM_PROVIDER")
        or getattr(settings, "llm_provider", "ollama")
        or "ollama"
    ).casefold()

    target_model = (
        model
        or os.environ.get("LLM_MODEL")
        or getattr(settings, "llm_model", "llama3.1")
        or "llama3.1"
    )

    target_key = (
        api_key
        or os.environ.get("LLM_API_KEY")
        or getattr(settings, "llm_api_key", "")
        or getattr(settings, "openai_api_key", "")
    )

    target_base = (
        base_url
        or os.environ.get("LLM_API_BASE")
        or getattr(settings, "llm_api_base", "")
    )

    target_temp = (
        temperature
        if temperature is not None
        else getattr(settings, "llm_temperature", 0.3)
    )

    if target_provider in {"ollama", "local"}:
        return _get_local_llm(model=target_model, temperature=target_temp, base_url=target_base)

    if target_provider == "openai":
        if not target_key:
            logger.warning("OpenAI provider selected but no API key provided. Falling back to local Ollama LLM.")
            return _get_local_llm(temperature=target_temp)
        try:
            kwargs: dict[str, Any] = {
                "model": target_model or "gpt-4o-mini",
                "api_key": target_key,
                "temperature": target_temp,
            }
            if target_base:
                kwargs["base_url"] = target_base
            return ChatOpenAI(**kwargs)
        except Exception as exc:
            logger.warning("Failed to initialize ChatOpenAI (%s). Falling back to local Ollama LLM.", exc)
            return _get_local_llm(temperature=target_temp)

    if target_provider in {"google", "gemini"}:
        if not target_key:
            logger.warning("Google provider selected but no API key provided. Falling back to local Ollama LLM.")
            return _get_local_llm(temperature=target_temp)
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI

            return ChatGoogleGenerativeAI(
                model=target_model or "gemini-1.5-flash",
                google_api_key=target_key,
                temperature=target_temp,
            )
        except Exception as exc:
            logger.warning("Failed to initialize ChatGoogleGenerativeAI (%s). Falling back to local Ollama LLM.", exc)
            return _get_local_llm(temperature=target_temp)

    if target_provider == "anthropic":
        if not target_key:
            logger.warning("Anthropic provider selected but no API key provided. Falling back to local Ollama LLM.")
            return _get_local_llm(temperature=target_temp)
        try:
            from langchain_anthropic import ChatAnthropic

            return ChatAnthropic(
                model=target_model or "claude-3-5-sonnet-20240620",
                api_key=target_key,
                temperature=target_temp,
            )
        except Exception as exc:
            logger.warning("Failed to initialize ChatAnthropic (%s). Falling back to local Ollama LLM.", exc)
            return _get_local_llm(temperature=target_temp)

    logger.warning("Unknown LLM provider '%s'. Falling back to local Ollama LLM.", target_provider)
    return _get_local_llm(temperature=target_temp)


@lru_cache
def get_embeddings(
    provider: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
) -> Embeddings:
    """Return configured Embeddings instance with local Ollama fallback.

    Args:
        provider: Provider name ("ollama", "openai", "google", "gemini").
        model: Model name string (e.g. "bge-m3", "text-embedding-3-small").
        api_key: API key for remote providers.
        base_url: Custom API endpoint base URL.
    """
    settings = get_settings()

    target_provider = (
        provider
        or os.environ.get("EMBEDDING_PROVIDER")
        or getattr(settings, "embedding_provider", "ollama")
        or "ollama"
    ).casefold()

    target_model = (
        model
        or os.environ.get("EMBEDDING_MODEL")
        or getattr(settings, "embedding_model", "bge-m3")
        or "bge-m3"
    )

    target_key = (
        api_key
        or os.environ.get("EMBEDDING_API_KEY")
        or getattr(settings, "embedding_api_key", "")
        or getattr(settings, "openai_api_key", "")
    )

    target_base = (
        base_url
        or os.environ.get("EMBEDDING_API_BASE")
        or getattr(settings, "embedding_api_base", "")
    )

    if target_provider in {"ollama", "local"}:
        return _get_local_embeddings(model=target_model, base_url=target_base)

    if target_provider == "openai":
        if not target_key:
            logger.warning("OpenAI embedding provider selected but no API key provided. Falling back to local OllamaEmbeddings.")
            return _get_local_embeddings()
        try:
            kwargs: dict[str, Any] = {
                "model": target_model or "text-embedding-3-small",
                "api_key": target_key,
            }
            if target_base:
                kwargs["base_url"] = target_base
            return OpenAIEmbeddings(**kwargs)
        except Exception as exc:
            logger.warning("Failed to initialize OpenAIEmbeddings (%s). Falling back to local OllamaEmbeddings.", exc)
            return _get_local_embeddings()

    if target_provider in {"google", "gemini"}:
        if not target_key:
            logger.warning("Google embedding provider selected but no API key provided. Falling back to local OllamaEmbeddings.")
            return _get_local_embeddings()
        try:
            from langchain_google_genai import GoogleGenerativeAIEmbeddings

            return GoogleGenerativeAIEmbeddings(
                model=target_model or "models/text-embedding-004",
                google_api_key=target_key,
            )
        except Exception as exc:
            logger.warning("Failed to initialize GoogleGenerativeAIEmbeddings (%s). Falling back to local OllamaEmbeddings.", exc)
            return _get_local_embeddings()

    logger.warning("Unknown embedding provider '%s'. Falling back to local OllamaEmbeddings.", target_provider)
    return _get_local_embeddings()
