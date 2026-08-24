"""Unit tests for local Supabase JWT verification — both code paths in
src/auth/jwt_verifier.py:

- JWKS/ES256 (the default, and what THIS project's live Supabase instance
  actually uses — verified 2026-08-14 by fetching its real
  {SUPABASE_URL}/auth/v1/.well-known/jwks.json).
- HS256 shared-secret (the legacy opt-in fallback, SUPABASE_JWT_SECRET set).

No live Supabase project or network access needed for either: HS256 tokens
are signed here with a test secret via PyJWT directly; JWKS tokens are signed
with a locally generated EC keypair, with jwt_verifier._jwks_client()
monkeypatched to hand back the matching public key instead of fetching a
real JWKS endpoint.
"""

import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

import src.auth.jwt_verifier as jwt_verifier
from src.auth.jwt_verifier import TokenVerificationError, verify_access_token
from src.config import get_settings

_SECRET = "test-jwt-secret-that-is-at-least-32-bytes-long"
_SUPABASE_URL = "https://example.supabase.co"
_ISSUER = f"{_SUPABASE_URL}/auth/v1"


@pytest.fixture(autouse=True)
def _configured_settings(monkeypatch):
    """Point settings at a test URL for every test in this module — same
    reset pattern as tests/test_llm_provider.py's _default_provider_settings
    (get_settings() is @lru_cache'd, so both the env and the cached Settings
    object need resetting). SUPABASE_JWT_SECRET is cleared by default so the
    JWKS path (the real default) is what most tests exercise; the HS256
    tests below opt back into the secret explicitly.
    """
    monkeypatch.setenv("SUPABASE_URL", _SUPABASE_URL)
    monkeypatch.delenv("SUPABASE_JWT_SECRET", raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _payload(**extra_claims):
    now = int(time.time())
    return {
        "sub": "user-123",
        "aud": "authenticated",
        "iss": _ISSUER,
        "iat": now,
        "exp": now + 3600,
        **extra_claims,
    }


def _make_hs256_token(*, secret=_SECRET, **extra_claims):
    return jwt.encode(_payload(**extra_claims), secret, algorithm="HS256")


# ---------------------------------------------------------------------------
# JWKS / ES256 — the default path, and what the live project actually uses
# ---------------------------------------------------------------------------


class _FakeJwksClient:
    """Stands in for jwt.PyJWKClient: hands back a fixed public key instead
    of fetching a real JWKS endpoint over the network."""

    def __init__(self, public_key):
        self._public_key = public_key

    def get_signing_key_from_jwt(self, _token):
        return SimpleNamespace(key=self._public_key)


def _make_es256_keypair():
    private_key = ec.generate_private_key(ec.SECP256R1())
    return private_key, private_key.public_key()


def _make_es256_token(private_key, **extra_claims):
    return jwt.encode(_payload(**extra_claims), private_key, algorithm="ES256")


def _use_fake_jwks(monkeypatch, public_key):
    monkeypatch.setattr(jwt_verifier, "_jwks_client", lambda _url: _FakeJwksClient(public_key))


def test_jwks_path_accepts_a_validly_signed_permanent_user_token(monkeypatch):
    private_key, public_key = _make_es256_keypair()
    _use_fake_jwks(monkeypatch, public_key)
    token = _make_es256_token(private_key, email="person@example.com")

    claims = verify_access_token(token)

    assert claims.user_id == "user-123"
    assert claims.email == "person@example.com"
    assert claims.is_anonymous is False


def test_jwks_path_reads_the_anonymous_claim(monkeypatch):
    private_key, public_key = _make_es256_keypair()
    _use_fake_jwks(monkeypatch, public_key)
    token = _make_es256_token(private_key, is_anonymous=True, email=None)

    claims = verify_access_token(token)

    assert claims.is_anonymous is True


def test_jwks_path_reads_app_metadata_role(monkeypatch):
    private_key, public_key = _make_es256_keypair()
    _use_fake_jwks(monkeypatch, public_key)
    token = _make_es256_token(private_key, app_metadata={"role": "admin"})

    claims = verify_access_token(token)

    assert claims.app_role == "admin"


def test_jwks_path_app_role_is_none_when_app_metadata_absent(monkeypatch):
    private_key, public_key = _make_es256_keypair()
    _use_fake_jwks(monkeypatch, public_key)
    token = _make_es256_token(private_key)

    claims = verify_access_token(token)

    assert claims.app_role is None


def test_jwks_path_app_role_is_none_when_app_metadata_is_not_a_dict(monkeypatch):
    """Defensive: a malformed/legacy token whose app_metadata isn't an object
    must not crash claim extraction -- it must simply carry no role."""
    private_key, public_key = _make_es256_keypair()
    _use_fake_jwks(monkeypatch, public_key)
    token = _make_es256_token(private_key, app_metadata="not-an-object")

    claims = verify_access_token(token)

    assert claims.app_role is None


def test_jwks_path_tolerates_a_token_issued_slightly_in_the_future(monkeypatch):
    """Regression test for a bug caught live (2026-08-14): a session created
    immediately after minting a real Supabase token failed with
    jwt.ImmatureSignatureError purely from sub-second clock drift between
    this backend's host and Supabase's auth server. A small leeway on
    exp/iat/nbf is the fix — assert it actually tolerates a token whose `iat`
    is a few seconds ahead of this process's clock, well within
    _CLOCK_SKEW_LEEWAY_SECONDS but outside zero tolerance."""
    private_key, public_key = _make_es256_keypair()
    _use_fake_jwks(monkeypatch, public_key)
    now = int(time.time())
    token = jwt.encode(
        {"sub": "user-123", "aud": "authenticated", "iss": _ISSUER, "iat": now + 5, "exp": now + 3600},
        private_key,
        algorithm="ES256",
    )

    claims = verify_access_token(token)

    assert claims.user_id == "user-123"


def test_jwks_path_still_rejects_a_token_issued_far_in_the_future(monkeypatch):
    """The leeway is a tolerance, not a blank check — a token claiming to be
    issued well beyond any plausible clock drift must still fail."""
    private_key, public_key = _make_es256_keypair()
    _use_fake_jwks(monkeypatch, public_key)
    now = int(time.time())
    token = jwt.encode(
        {"sub": "user-123", "aud": "authenticated", "iss": _ISSUER, "iat": now + 3600, "exp": now + 7200},
        private_key,
        algorithm="ES256",
    )

    with pytest.raises(TokenVerificationError):
        verify_access_token(token)


def test_jwks_path_rejects_a_token_signed_with_a_different_keypair(monkeypatch):
    _, public_key = _make_es256_keypair()
    other_private_key, _ = _make_es256_keypair()
    _use_fake_jwks(monkeypatch, public_key)
    token = _make_es256_token(other_private_key)

    with pytest.raises(TokenVerificationError):
        verify_access_token(token)


def test_jwks_path_rejects_an_expired_token(monkeypatch):
    private_key, public_key = _make_es256_keypair()
    _use_fake_jwks(monkeypatch, public_key)
    now = int(time.time())
    token = jwt.encode(
        {"sub": "user-123", "aud": "authenticated", "iss": _ISSUER, "iat": now, "exp": now - 60},
        private_key,
        algorithm="ES256",
    )

    with pytest.raises(TokenVerificationError):
        verify_access_token(token)


def test_jwks_path_rejects_the_wrong_issuer(monkeypatch):
    private_key, public_key = _make_es256_keypair()
    _use_fake_jwks(monkeypatch, public_key)
    token = _make_es256_token(private_key, iss="https://not-this-project.supabase.co/auth/v1")

    with pytest.raises(TokenVerificationError):
        verify_access_token(token)


def test_jwks_path_wraps_client_errors_without_leaking_detail(monkeypatch):
    """An unreachable/misconfigured JWKS endpoint (network error, unknown
    kid) must degrade to the same safe-to-surface TokenVerificationError as
    every other failure — never a raw PyJWKClientError."""
    from jwt import PyJWKClientError

    class _BrokenJwksClient:
        def get_signing_key_from_jwt(self, _token):
            raise PyJWKClientError("could not reach jwks endpoint: connection refused")

    monkeypatch.setattr(jwt_verifier, "_jwks_client", lambda _url: _BrokenJwksClient())
    private_key, _ = _make_es256_keypair()
    token = _make_es256_token(private_key)

    with pytest.raises(TokenVerificationError):
        verify_access_token(token)


def test_no_supabase_url_configured_raises(monkeypatch):
    # Patched directly rather than via monkeypatch.delenv("SUPABASE_URL"):
    # Settings.model_config reads backend/.env directly (env_file=".env"),
    # which — in this repo, on a dev machine with the real project
    # configured — still supplies a real value even once the env var itself
    # is unset. Patching _expected_issuer() is what actually exercises "no
    # issuer resolvable" regardless of what's on disk.
    monkeypatch.setattr(jwt_verifier, "_expected_issuer", lambda: None)

    with pytest.raises(TokenVerificationError):
        verify_access_token("anything")


def test_empty_token_raises():
    with pytest.raises(TokenVerificationError):
        verify_access_token("")


def test_jwks_path_wraps_a_malformed_token_without_leaking_a_raw_decode_error(monkeypatch):
    """get_signing_key_from_jwt() does an unverified decode of the token to
    read its header before any key lookup — a garbled token must still come
    out as TokenVerificationError, not a raw jwt.exceptions.DecodeError."""
    with pytest.raises(TokenVerificationError):
        verify_access_token("not-a-real-jwt-at-all")


# ---------------------------------------------------------------------------
# HS256 shared secret — legacy opt-in fallback (SUPABASE_JWT_SECRET set)
# ---------------------------------------------------------------------------


def test_hs256_path_accepts_a_validly_signed_token_when_secret_is_configured(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", _SECRET)
    get_settings.cache_clear()
    token = _make_hs256_token(email="person@example.com")

    claims = verify_access_token(token)

    assert claims.user_id == "user-123"
    assert claims.email == "person@example.com"


def test_hs256_path_rejects_a_token_signed_with_a_different_secret(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", _SECRET)
    get_settings.cache_clear()
    token = _make_hs256_token(secret="not-the-real-secret-and-also-32-bytes")

    with pytest.raises(TokenVerificationError):
        verify_access_token(token)


def test_hs256_path_rejects_an_expired_token(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", _SECRET)
    get_settings.cache_clear()
    now = int(time.time())
    token = jwt.encode(
        {"sub": "user-123", "aud": "authenticated", "iss": _ISSUER, "iat": now, "exp": now - 60},
        _SECRET,
        algorithm="HS256",
    )

    with pytest.raises(TokenVerificationError):
        verify_access_token(token)


def test_hs256_path_rejects_the_wrong_audience(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", _SECRET)
    get_settings.cache_clear()
    token = _make_hs256_token(aud="some-other-audience")

    with pytest.raises(TokenVerificationError):
        verify_access_token(token)


def test_hs256_path_rejects_a_token_missing_sub(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", _SECRET)
    get_settings.cache_clear()
    now = int(time.time())
    token = jwt.encode(
        {"aud": "authenticated", "iss": _ISSUER, "iat": now, "exp": now + 3600},
        _SECRET,
        algorithm="HS256",
    )

    with pytest.raises(TokenVerificationError):
        verify_access_token(token)
