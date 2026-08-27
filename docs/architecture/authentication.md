# Authentication & Authorization

Plan: `260814-supabase-auth-and-per-user-history`. Code: `backend/src/auth/`.
Contract-level detail: [`../chat_api_contract.md`](../chat_api_contract.md) § Authentication.

---

## Identity model

Every visitor — anonymous or permanent — holds a **real Supabase-issued JWT**.

- **Guests** get one transparently via Supabase **Anonymous Auth**
  (`supabase.auth.signInAnonymously()` on the frontend). `current_user` is a genuine
  identity even before someone registers.
- **Registering / logging in** from an anonymous session **upgrades the same
  `auth.users` row in place** (`updateUser` / `linkIdentity`, not a fresh `signUp`), so a
  guest's chat history survives account creation — it was never keyed by anything else.
- `sessions.user_id` → `auth.users.id` (nullable: rows predating this plan, or created
  outside the HTTP API such as the CLI, have no owner).

## Token verification — local, no per-request Auth API call

`backend/src/auth/jwt_verifier.py`. FastAPI handlers in `routes.py` are plain `def`
(blocking work runs in the worker pool), so a mandatory network round-trip to the
Supabase Auth API on every request would fight that design. Verification is local:

- **Primary path: JWKS (asymmetric).** This project's Supabase instance publishes a real
  **ES256** key at `{SUPABASE_URL}/auth/v1/.well-known/jwks.json` (confirmed 2026-08-14).
  PyJWT's `PyJWKClient` verifies the signature; its 5-minute in-memory cache means this
  is **not** a network call on every request — only on a cache miss or an unknown `kid`.
  Accepted algorithms: `ES256`, `RS256`.
- **Fallback: HS256 shared secret** via `SUPABASE_JWT_SECRET`. Opt-in only, for pointing
  the backend at an older Supabase project that still uses the legacy shared secret.
  **This project does not set it.** It is never sent to Supabase and is unrelated to
  `SUPABASE_SERVICE_KEY` (which is the Postgres/PostgREST client key).
- Standard claims checked: `exp`, `iat`, `nbf`, `aud` (always `"authenticated"` for
  Supabase, anonymous sessions included), `iss`. A **30-second clock-skew leeway** is
  applied on `exp`/`iat`/`nbf` (sub-second host↔Supabase drift otherwise throws
  `ImmatureSignatureError`).
- **Trade-off accepted:** a token revoked out-of-band stays valid here until its natural
  expiry (Supabase default: 1 hour). Acceptable for a trip planner; not a substitute for
  a stricter instant-revocation design.

`TokenVerificationError` messages are safe to show the caller — they never wrap a raw
PyJWT exception (which can echo token fragments).

## `AUTH_REQUIRED` — the rollout flag

`backend/.env`, default **`false`**. Governs **only** what happens to a request with
**no or an invalid token**:

| `AUTH_REQUIRED` | No/invalid token | Valid token |
|---|---|---|
| `false` (default) | treated as no caller identity (`current_user = None`), request proceeds | always honored, always identifies the caller |
| `true` | `401 {"detail": "Chưa đăng nhập hoặc phiên đăng nhập không hợp lệ."}` | same |

A **valid** token is always trusted regardless of the flag — it only ever relaxes the
no-token case. Flip to `true` only once the frontend is confirmed sending
`Authorization: Bearer <token>` on every session-scoped call. (Mirrors
`SESSION_PERSISTENCE_ENABLED`'s ship-then-enforce pattern.)

## Route dependencies

| Dependency | Module | Behavior |
|---|---|---|
| `get_current_user` | `auth/dependencies.py` | Returns `AuthenticatedUser` for a valid token; `None` when the token is missing/invalid **and** `AUTH_REQUIRED=false`; raises `401` when missing/invalid **and** `AUTH_REQUIRED=true`. Used by all session-scoped chat endpoints. |
| `require_admin` | `auth/admin.py` | **Always strict**, ignores `AUTH_REQUIRED`. No/invalid token → `401`; valid token whose claims are anonymous or whose `app_role != "admin"` → `403`. Applied to the whole `/api/v1/admin` router as a router-level dependency. |

Admin authorization is deliberately a **separate module** from `get_current_user` so the
"permissive rollout" vs "always strict" boundary is visible at a glance. An admin's role
comes from the `app_role` claim in the Supabase JWT (`app_metadata`), value `"admin"`.

## Ownership semantics — 404, never 403

A session with an owner (`sessions.user_id`) is reachable **only** by that same caller.
A mismatch — a different authenticated user, or no identity at all — returns the same
`404 {"detail": "Phiên chat không tồn tại."}` used for a genuinely unknown `session_id`,
**never `403`**: a distinct status would itself leak "this session_id is real, just not
yours" (enumeration side channel).

Sessions with **no** owner (legacy / CLI-created rows) stay reachable by any caller —
a deliberate, permissive gap for out-of-band sessions, not something to lock with `403`.

`DELETE /chat/{session_id}` keeps its "`204` whether it exists or not" contract: a
session owned by someone else is a **silent no-op** (`204`, nothing deleted), same
anti-enumeration reason.

**Applies to:** `POST /chat/session` (stamps the caller as owner), `GET /chat/sessions`
(scoped to the caller — previously returned every session in the DB), `GET
/chat/{id}/restore`, `GET /chat/{id}/plan` (+ `/session/{id}/state`), `POST
/planner_chat` (+ `/chat`), `POST /planner_chat/stream`, `POST /hotels/select` (+
`/chat/select_hotel`), `POST /hotels/change`.

Sessionless catalog lookups (`GET /hotels/{id}`, `/attractions/{id}`,
`/search_attractions`, `/search_hotels`, `/status`) carry no per-user data and are
unaffected.

## Out of scope for the backend

Token issuance / refresh / OAuth is entirely a frontend ↔ Supabase Auth concern
(`frontend/src/auth/`). This backend only ever **verifies** a token it is handed.

## Environment variables

See [`../setup/environment-variables.md`](../setup/environment-variables.md). Relevant:
`SUPABASE_URL` (required — also the JWKS host), `AUTH_REQUIRED`, `SUPABASE_JWT_SECRET`
(leave blank for this project).
