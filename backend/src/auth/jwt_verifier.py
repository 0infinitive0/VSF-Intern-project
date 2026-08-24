"""Local verification of Supabase-issued access tokens.

Every FastAPI handler in src/api/routes.py is deliberately a plain `def`, not
`async def`, so blocking work (Supabase/LLM calls) runs in the worker thread
pool without stalling the event loop (see routes.py's module docstring). A
mandatory network round-trip to the Supabase Auth API on *every* request
(`supabase.auth.get_user(token)`) would fight that design directly and couple
every request's latency/availability to the Auth API. Supabase's own
recommended pattern for backend services is local verification instead: a
signing key verifies the token's signature and standard claims (exp/aud/iss)
without calling the Auth API per request.

Trade-off accepted: a token revoked out-of-band (e.g. a user manually
invalidated elsewhere) stays "valid" here until its own short natural expiry
(Supabase default: 1 hour) rather than failing instantly. Acceptable for a
trip planner; not a substitute for local verification in a system with a
stricter instant-revocation requirement.

Key resolution — checked against the live project (2026-08-14), not assumed:
fetching `{SUPABASE_URL}/auth/v1/.well-known/jwks.json` returned a real
ES256/P-256 key, confirming this project uses Supabase's modern **asymmetric
per-project signing keys**, not the legacy shared HS256 secret. So the
primary path here is JWKS verification via PyJWT's `PyJWKClient` (its own
5-minute in-memory cache means this is NOT a network call on every request —
only on a cache miss or an unrecognized `kid`). `SUPABASE_JWT_SECRET` stays
supported as an explicit opt-in fallback (HS256, legacy projects) purely for
portability if this code is ever pointed at an older Supabase project — this
project does not need to set it, and backend/.env.example documents that.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import jwt
from jwt import PyJWKClient, PyJWKClientError

from src.config import get_settings

# Supabase always issues access tokens with this fixed audience for
# authenticated (including anonymous) sessions.
_EXPECTED_AUDIENCE = "authenticated"
# Both are accepted since Supabase projects may use either asymmetric
# algorithm for their signing keys depending on when/how the project was
# provisioned; PyJWT requires an explicit allowlist regardless of what the
# resolved key's own metadata claims.
_ASYMMETRIC_ALGORITHMS = ["ES256", "RS256"]

# PyJWT's default leeway is 0 — it rejects a token the instant its `exp` has
# passed, and, more surprisingly, rejects one the instant BEFORE its `iat`
# if the verifying machine's clock reads even slightly earlier than the
# issuing server's. Caught live (2026-08-14): a session created immediately
# after minting a fresh Supabase token failed with jwt.ImmatureSignatureError
# ("token is not yet valid (iat)") purely from sub-second clock drift between
# this backend's host and Supabase's auth server — completely ordinary for
# two independent machines, not a sign either clock is "wrong". A small
# leeway on both exp/iat/nbf checks is the standard fix (every major JWT
# library recommends one for exactly this).
_CLOCK_SKEW_LEEWAY_SECONDS = 30


class TokenVerificationError(Exception):
    """Raised for any invalid/missing/expired token. Message is safe to show
    the caller as-is (never wraps a raw pyjwt exception message, which can
    include token fragments)."""


@dataclass(frozen=True)
class SupabaseClaims:
    """The subset of a verified Supabase JWT's claims this app actually uses."""

    user_id: str
    email: str | None
    is_anonymous: bool
    # From payload["app_metadata"]["role"] -- NEVER "user_metadata": that
    # object is writable by the end user themselves via
    # supabase.auth.updateUser(), so reading role from it would let any
    # caller self-grant admin. app_metadata is only settable with a
    # service-role key, from outside the end user's own session.
    app_role: str | None


def _expected_issuer() -> str | None:
    base = get_settings().supabase_url.rstrip("/")
    if not base:
        return None
    return f"{base}/auth/v1"


@lru_cache(maxsize=4)
def _jwks_client(jwks_url: str) -> PyJWKClient:
    # One client per URL, reused across requests for the lifetime of the
    # process — this is what makes JWKS verification cheap: PyJWKClient
    # caches the fetched key set itself (5 min default) rather than this
    # function re-fetching per call.
    return PyJWKClient(jwks_url, cache_keys=True)


def _decode_with_shared_secret(token: str, secret: str, issuer: str | None) -> dict:
    try:
        return jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            audience=_EXPECTED_AUDIENCE,
            issuer=issuer,
            leeway=_CLOCK_SKEW_LEEWAY_SECONDS,
            options={"require": ["exp", "sub", "aud"]},
        )
    except jwt.PyJWTError as exc:
        raise TokenVerificationError("Invalid or expired session.") from exc


def _decode_with_jwks(token: str, issuer: str, jwks_url: str) -> dict:
    try:
        signing_key = _jwks_client(jwks_url).get_signing_key_from_jwt(token)
    except (PyJWKClientError, jwt.PyJWTError) as exc:
        # PyJWKClientError covers "endpoint unreachable" / "no key matches
        # this token's kid"; get_signing_key_from_jwt() also does an
        # unverified decode of the token first to read its header, which
        # raises plain PyJWTError subclasses (e.g. DecodeError) for a
        # malformed token before any key lookup happens at all. Neither
        # should ever surface raw exception detail to a caller.
        raise TokenVerificationError("Unable to verify session.") from exc
    try:
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=_ASYMMETRIC_ALGORITHMS,
            audience=_EXPECTED_AUDIENCE,
            issuer=issuer,
            leeway=_CLOCK_SKEW_LEEWAY_SECONDS,
            options={"require": ["exp", "sub", "aud"]},
        )
    except jwt.PyJWTError as exc:
        raise TokenVerificationError("Invalid or expired session.") from exc


def _decode(token: str) -> dict:
    issuer = _expected_issuer()
    if not issuer:
        raise TokenVerificationError("Auth is not configured on this server.")

    secret = get_settings().supabase_jwt_secret
    if secret:
        return _decode_with_shared_secret(token, secret, issuer)
    return _decode_with_jwks(token, issuer, f"{issuer}/.well-known/jwks.json")


def verify_access_token(token: str) -> SupabaseClaims:
    """Verify a Supabase access token and return the claims this app needs.

    Raises TokenVerificationError (safe to surface directly) on any failure:
    missing/garbled token, bad signature, expired, wrong audience/issuer,
    or an unreachable/misconfigured JWKS endpoint.
    """
    if not token:
        raise TokenVerificationError("Missing session token.")
    payload = _decode(token)
    user_id = payload.get("sub")
    if not user_id:
        raise TokenVerificationError("Invalid session token.")
    app_metadata = payload.get("app_metadata")
    app_role = app_metadata.get("role") if isinstance(app_metadata, dict) else None
    return SupabaseClaims(
        user_id=user_id,
        email=payload.get("email"),
        # Supabase sets this claim to true on anonymous sessions
        # (https://supabase.com/docs/guides/auth/auth-anonymous); absent
        # entirely on permanent accounts, hence the explicit bool() default.
        is_anonymous=bool(payload.get("is_anonymous", False)),
        app_role=str(app_role) if app_role is not None else None,
    )
