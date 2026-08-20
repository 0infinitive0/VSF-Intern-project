"""Stops the suite from reaching a real LLM provider.

Nine tests currently open a live connection to api.openai.com, which costs money
and makes the run depend on a key being present. Setting TEST_SKIP_LLM in
backend/.env turns those calls into skips: any attempt to resolve or connect to
a provider host raises pytest's Skipped outcome, so the test reports as skipped
instead of failing or spending. Everything else — Supabase, local transports —
is untouched.

Skipped is a BaseException, so it travels through the application's own
`except Exception` handlers rather than being swallowed and retried.
"""

import os
import socket
from pathlib import Path

import pytest
from dotenv import dotenv_values

# Hosted inference endpoints. A local provider (Ollama on 127.0.0.1) is not an
# LLM cost or a network dependency, so it is deliberately absent.
LLM_HOSTS = frozenset(
    {
        "api.openai.com",
        "api.anthropic.com",
        "openrouter.ai",
        "api.groq.com",
        "api.cohere.ai",
        "generativelanguage.googleapis.com",
    }
)

_ENV_VAR = "TEST_SKIP_LLM"
_TRUTHY = {"1", "true", "yes", "on"}

_installed = False


def _env_file_value(name: str) -> str | None:
    """Read one key from backend/.env without importing its secrets into os.environ."""
    env_file = Path(__file__).resolve().parent.parent / ".env"
    if not env_file.is_file():
        return None
    return dotenv_values(env_file).get(name)


def enabled() -> bool:
    """True when the suite should run without touching a hosted LLM.

    A real environment variable wins over backend/.env so CI and one-off runs
    can flip it without editing a file.
    """
    value = os.environ.get(_ENV_VAR)
    if value is None:
        value = _env_file_value(_ENV_VAR)
    return (value or "").strip().lower() in _TRUTHY


def _skip(host: object) -> None:
    pytest.skip(f"{_ENV_VAR} is set; this test needs a live LLM call to {host}")


def install() -> None:
    """Patch the socket layer so LLM provider traffic skips the test instead."""
    global _installed
    if _installed:
        return
    _installed = True

    real_connect = socket.socket.connect
    real_getaddrinfo = socket.getaddrinfo

    def guarded_connect(self, address, *args, **kwargs):
        host = address[0] if isinstance(address, tuple) else address
        if str(host) in LLM_HOSTS:
            _skip(host)
        return real_connect(self, address, *args, **kwargs)

    def guarded_getaddrinfo(host, *args, **kwargs):
        if str(host) in LLM_HOSTS:
            _skip(host)
        return real_getaddrinfo(host, *args, **kwargs)

    socket.socket.connect = guarded_connect
    socket.getaddrinfo = guarded_getaddrinfo
