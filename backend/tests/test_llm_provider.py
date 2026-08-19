"""Unit tests for configurable LLM and Embedding factories with local fallback."""

import os
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage
from langchain_ollama import ChatOllama, OllamaEmbeddings
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from src.config import Settings, get_settings
from src.services.llm import (
    get_embeddings,
    get_fast_llm,
    get_llm,
    get_reasoning_llm,
    response_text,
)

_PROVIDER_ENV_PREFIXES = ("LLM_", "EMBEDDING_")
_PROVIDER_ENV_KEYS = ("OPENAI_API_KEY", "OPENROUTER_API_KEY", "OPENAI_BASE_URL")


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


def test_role_specific_llms_use_their_configured_models(monkeypatch):
    """The fast path must not accidentally consume the reasoning-model budget."""
    monkeypatch.setenv("LLM_REASONING_MODEL", "reasoning-model")
    monkeypatch.setenv("LLM_FAST_MODEL", "fast-model")

    with patch("src.services.llm.get_llm") as factory:
        get_reasoning_llm(temperature=0.0)
        get_fast_llm(temperature=0.7)

    assert factory.call_args_list[0].kwargs == {"model": "reasoning-model", "temperature": 0.0}
    assert factory.call_args_list[1].kwargs == {"model": "fast-model", "temperature": 0.7}


def test_role_specific_llm_allows_an_explicit_model_override(monkeypatch):
    monkeypatch.setenv("LLM_FAST_MODEL", "fast-model")

    with patch("src.services.llm.get_llm") as factory:
        get_fast_llm(model="test-model")

    assert factory.call_args.kwargs["model"] == "test-model"


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


@pytest.mark.parametrize("model", ["gpt-5", "o1", "o3-mini", "o4-mini"])
def test_get_llm_omits_temperature_for_models_that_only_allow_default(model: str):
    """Reasoning models reject explicit non-default temperature values."""
    with patch("src.services.llm.ChatOpenAI") as factory:
        get_llm(provider="openai", model=model, api_key="sk-dummykey123", temperature=0.0)

    assert "temperature" not in factory.call_args.kwargs


def test_get_llm_keeps_temperature_for_models_that_support_it():
    with patch("src.services.llm.ChatOpenAI") as factory:
        get_llm(provider="openai", model="gpt-4o-mini", api_key="sk-dummykey123", temperature=0.3)

    assert factory.call_args.kwargs["temperature"] == 0.3


@pytest.mark.parametrize("model", ["gpt-5", "o1", "o3-mini", "o4-mini"])
def test_get_llm_defaults_reasoning_effort_to_low_for_reasoning_models(model: str):
    """Regression: the API's own default ('medium') measured 76s/1536 hidden reasoning
    tokens to answer a plain capabilities question in qa_node -- 89% of that turn's
    latency. 'low' is the safe default until a call site opts into something heavier."""
    with patch("src.services.llm.ChatOpenAI") as factory:
        get_llm(provider="openai", model=model, api_key="sk-dummykey123")

    assert factory.call_args.kwargs["reasoning_effort"] == "low"


def test_get_llm_omits_reasoning_effort_for_models_that_reject_it():
    with patch("src.services.llm.ChatOpenAI") as factory:
        get_llm(provider="openai", model="gpt-4o-mini", api_key="sk-dummykey123")

    assert "reasoning_effort" not in factory.call_args.kwargs


def test_get_llm_reasoning_effort_configurable_via_env(monkeypatch):
    monkeypatch.setenv("LLM_REASONING_EFFORT", "high")
    get_settings.cache_clear()
    try:
        with patch("src.services.llm.ChatOpenAI") as factory:
            get_llm(provider="openai", model="gpt-5", api_key="sk-dummykey123")
        assert factory.call_args.kwargs["reasoning_effort"] == "high"
    finally:
        get_settings.cache_clear()


def test_get_llm_reasoning_effort_explicit_override_wins_over_env(monkeypatch):
    monkeypatch.setenv("LLM_REASONING_EFFORT", "high")
    get_settings.cache_clear()
    try:
        with patch("src.services.llm.ChatOpenAI") as factory:
            get_llm(provider="openai", model="gpt-5", api_key="sk-dummykey123", reasoning_effort="minimal")
        assert factory.call_args.kwargs["reasoning_effort"] == "minimal"
    finally:
        get_settings.cache_clear()


def test_get_llm_streaming_unset_by_default():
    """No call site should get an implicit 'streaming' kwarg -- most nodes (supervisor,
    extract_patch) must NOT stream their JSON output to the client."""
    with patch("src.services.llm.ChatOpenAI") as factory:
        get_llm(provider="openai", model="gpt-4o-mini", api_key="sk-dummykey123")

    assert "streaming" not in factory.call_args.kwargs


def test_get_llm_streaming_opt_in():
    with patch("src.services.llm.ChatOpenAI") as factory:
        get_llm(provider="openai", model="gpt-4o-mini", api_key="sk-dummykey123", streaming=True)

    assert factory.call_args.kwargs["streaming"] is True


def test_get_fast_llm_streaming_opt_in_reaches_get_llm():
    """qa_node/intake_qa pass streaming=True explicitly; other callers (e.g. supervisor)
    that omit it must produce the exact same kwargs as before this feature existed."""
    with patch("src.services.llm.get_llm") as factory:
        get_fast_llm(temperature=0.2, streaming=True)

    assert factory.call_args.kwargs["streaming"] is True


def test_openai_instance_reports_streamed_token_usage():
    """A streamed OpenAI call must carry `stream_options.include_usage`, or the two
    streaming nodes (`qa_node`, `intake_qa`) report zero tokens and any cost figure
    derived from them is wrong by exactly their share of the spend.

    langchain-openai enables this itself for OpenAI-hosted endpoints, so this asserts
    an inherited default rather than a local one — which is the reason to pin it. The
    field's own declared default is `None`; the value below is set afterwards, during
    validation, and only when no custom base URL is in play.
    """
    llm = get_llm(provider="openai", model="gpt-4o-mini", api_key="sk-dummykey123")

    assert isinstance(llm, ChatOpenAI)
    assert llm.stream_usage is True


@pytest.mark.parametrize(
    ("provider", "api_key"),
    [("openrouter", "sk-or-dummy123"), ("cloudflare", "cf-dummy123")],
)
def test_custom_base_url_providers_do_not_request_streamed_usage(provider, api_key, monkeypatch):
    """The inverse of the test above, and the half that matters more.

    OpenRouter and Cloudflare build a `ChatOpenAI`-family object too, but neither is
    verified to accept `stream_options.include_usage` — `_CloudflareChatOpenAI` exists
    precisely because that endpoint's schema diverges from OpenAI's. Both configure a
    custom base URL, which is what keeps the option off. A later change that sets
    `stream_usage` unconditionally in `get_llm` would widen it to two endpoints nobody
    measured, so it has to fail here instead of in production.
    """
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "test-account")

    llm = get_llm(provider=provider, model="test-model", api_key=api_key)

    assert isinstance(llm, ChatOpenAI)
    assert llm.stream_usage is not True


class TestResponseText:
    """`response_text` is the one place that knows what shape `content` can be.

    Before it existed, eight call sites each assumed `str`, and every one of them
    sat inside a broad `except Exception` with a fallback — so a list-shaped
    answer degraded the reply silently instead of failing loudly.
    """

    def test_a_plain_string_passes_through(self):
        assert response_text(AIMessage(content="xin chào")) == "xin chào"

    def test_text_blocks_are_joined_with_their_whitespace(self):
        message = AIMessage(
            content=[{"type": "text", "text": "Thủ đô "}, {"type": "text", "text": "là Hà Nội."}]
        )

        assert response_text(message) == "Thủ đô là Hà Nội."

    def test_reasoning_blocks_are_not_the_answer(self):
        """A reasoning summary is the model thinking out loud, not its reply.
        Letting it through would put English internal monologue into a
        Vietnamese answer — and, for the JSON call sites, into `json.loads`."""
        message = AIMessage(
            content=[
                {"type": "reasoning", "reasoning": "Working out the capital"},
                {"type": "text", "text": "Hà Nội."},
            ]
        )

        assert response_text(message) == "Hà Nội."

    def test_missing_or_empty_content_is_an_empty_string(self):
        assert response_text(AIMessage(content="")) == ""
        assert response_text(AIMessage(content=[])) == ""
        assert response_text(object()) == ""

    def test_a_bare_list_without_a_message_wrapper_still_works(self):
        """Some call sites pass `getattr(response, "content", response)` along,
        so the raw list can arrive here without its message."""
        assert response_text([{"type": "text", "text": "Hà Nội."}]) == "Hà Nội."

    def test_the_real_responses_api_chunk_shape(self):
        """Measured shape, not an invented one — see
        `plans/reports/probe-260819-responses-api-payload-and-usage.md` §2."""
        chunk = AIMessage(content=[{"type": "text", "text": " đô", "index": 1}])

        assert response_text(chunk) == " đô"


class TestResponsesApiOptIn:
    """`LLM_USE_RESPONSES_API` routes OpenAI calls through the Responses API.

    Default off, and narrower than the flag name suggests: only the reasoning
    family (`gpt-5`/`o1`/`o3`/`o4`) is switched. `gpt-4o-mini` rejects the
    reasoning parameters that come with that route with a 400 (measured
    2026-08-18), and it is the model `eval/harness/judge.py` hardcodes — so a
    provider-wide switch would take the whole eval harness down with it.
    """

    def test_a_reasoning_model_uses_it_by_default(self):
        llm = get_llm(provider="openai", model="gpt-5-mini", api_key="sk-dummykey123")

        assert isinstance(llm, ChatOpenAI)
        assert llm.use_responses_api is True

    def test_the_flag_is_the_rollback(self):
        """Turning it off has to keep working: it is the way back if the
        transport misbehaves, and it must not need a deploy."""
        import os
        from unittest.mock import patch

        with patch.dict(os.environ, {"LLM_USE_RESPONSES_API": "false"}):
            llm = get_llm(provider="openai", model="gpt-5-mini", api_key="sk-dummykey123")

        assert llm.use_responses_api is not True

    def test_it_leaves_stream_usage_alone(self, monkeypatch):
        """Measured 2026-08-19: the Responses API accepts the `stream_options`
        langchain sends for `stream_usage`, and reports usage either way. An
        earlier draft turned `stream_usage` off to dodge a 400 that does not
        happen — at the cost of every streamed call's token count, which is
        what `eval/harness/cost.py` prices a run from."""
        monkeypatch.setenv("LLM_USE_RESPONSES_API", "true")

        llm = get_llm(provider="openai", model="gpt-5-mini", api_key="sk-dummykey123")

        assert llm.stream_usage is True

    @pytest.mark.parametrize("model", ["gpt-4o-mini", "gpt-4o", "gpt-3.5-turbo"])
    def test_it_does_not_reach_models_outside_the_reasoning_family(self, model):
        llm = get_llm(provider="openai", model=model, api_key="sk-dummykey123")

        assert llm.use_responses_api is not True

    @pytest.mark.parametrize(
        ("provider", "api_key"),
        [("openrouter", "sk-or-dummy123"), ("cloudflare", "cf-dummy123")],
    )
    def test_it_does_not_reach_other_providers(self, provider, api_key, monkeypatch):
        """Both build a `ChatOpenAI`-family object, and neither endpoint
        implements the Responses API at all."""
        monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "test-account")

        llm = get_llm(provider=provider, model="gpt-5-mini", api_key=api_key)

        assert isinstance(llm, ChatOpenAI)
        assert llm.use_responses_api is not True

    def test_the_judge_config_is_unaffected(self):
        """`eval/harness/judge.py:19` calls exactly this. It answers the
        reasoning parameters this transport implies with a 400, so the default
        must never reach it."""
        llm = get_llm(provider="openai", model="gpt-4o-mini", temperature=0.0, api_key="sk-dummykey123")

        assert llm.use_responses_api is not True
        assert llm.temperature == 0.0


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
