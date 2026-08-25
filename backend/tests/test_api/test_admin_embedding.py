"""Tests for admin B7/C4 (Trạng thái & độ phủ embedding) -- src/api/admin/embedding.py
(phase-12-embedding-status.md). Self-contained in-memory postgrest fake, same
idiom as test_admin_room_prices.py's (`.is_()` support), plus `count="exact"`
and `.in_()` for the summary counts and the batch reembed write.
"""

from __future__ import annotations

import pytest

from src.api.admin import embedding as embedding_module
from src.auth import AdminUser, require_admin
from src.main import app


class _Response:
    def __init__(self, data, count=None):
        self.data = data
        self.count = count


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows
        self._eq: list[tuple[str, object]] = []
        self._in: list[tuple[str, list]] = []
        self._is: list[tuple[str, object]] = []
        self._count_exact = False
        self._start: int | None = None
        self._end: int | None = None
        self.update_payload: dict | None = None
        self.update_kwargs: dict | None = None
        self.order_calls: list[tuple[str, dict]] = []

    def select(self, *_args, count=None, **_kwargs):
        self._count_exact = count == "exact"
        return self

    def eq(self, field, value):
        self._eq.append((field, value))
        return self

    def in_(self, field, values):
        self._in.append((field, list(values)))
        return self

    def is_(self, field, value):
        self._is.append((field, value))
        return self

    def order(self, column, **kwargs):
        self.order_calls.append((column, kwargs))
        return self

    def limit(self, n):
        self._start, self._end = 0, n - 1
        return self

    def range(self, start, end):
        self._start, self._end = start, end
        return self

    def update(self, payload, **kwargs):
        self.update_payload = payload
        self.update_kwargs = kwargs
        return self

    def _matches(self, row) -> bool:
        for field, value in self._eq:
            if row.get(field) != value:
                return False
        for field, values in self._in:
            if row.get(field) not in values:
                return False
        for field, value in self._is:
            expects_none = value in (None, "null")
            if (row.get(field) is None) != expects_none:
                return False
        return True

    def execute(self):
        matched = [row for row in self._rows if self._matches(row)]
        if self.update_payload is not None:
            for row in matched:
                row.update(self.update_payload)
            return _Response(matched, count=len(matched))
        total = len(matched)
        if self._start is not None:
            matched = matched[self._start : self._end + 1]
        return _Response(matched, count=total if self._count_exact else None)


class _FakeClient:
    def __init__(self, tables: dict[str, list[dict]]):
        self._tables = tables
        self.table_calls: list[str] = []
        self.queries: dict[str, list[_FakeQuery]] = {}

    def table(self, name):
        self.table_calls.append(name)
        query = _FakeQuery(self._tables.setdefault(name, []))
        self.queries.setdefault(name, []).append(query)
        return query


@pytest.fixture
def admin_override():
    app.dependency_overrides[require_admin] = lambda: AdminUser(id="admin-1", email="admin@vsftrip.vn")
    yield
    app.dependency_overrides.pop(require_admin, None)


@pytest.fixture
def no_audit(monkeypatch):
    calls: list[dict] = []
    monkeypatch.setattr(embedding_module, "write_audit", lambda actor, **kwargs: calls.append({"actor": actor, **kwargs}))
    return calls


def _hotels(n_total: int, n_missing: int) -> list[dict]:
    return [{"id": f"h{i}", "embedding": None if i < n_missing else [0.1]} for i in range(n_total)]


def _rooms(n_total: int, n_missing: int) -> list[dict]:
    return [{"id": f"r{i}", "embedding": None if i < n_missing else [0.1]} for i in range(n_total)]


def _attractions(n_total: int, n_missing: int) -> list[dict]:
    return [{"id": f"a{i}", "embedding": None if i < n_missing else [0.1]} for i in range(n_total)]


# ---------------------------------------------------------------------------
# GET /api/v1/admin/embedding/summary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_summary_counts_match_missing_and_embedded_per_table(client, admin_override, monkeypatch):
    fake_client = _FakeClient(
        {
            "hotels": _hotels(64, 0),
            "rooms": _rooms(1246, 62),
            "attractions": _attractions(312, 0),
        }
    )
    monkeypatch.setattr(embedding_module, "get_supabase_client", lambda: fake_client)

    response = await client.get("/api/v1/admin/embedding/summary")

    assert response.status_code == 200
    body = response.json()
    by_table = {t["table"]: t for t in body["tables"]}
    assert by_table["hotels"] == {"table": "hotels", "label": "Khách sạn", "total": 64, "embedded": 64, "missing": 0}
    assert by_table["rooms"] == {"table": "rooms", "label": "Phòng", "total": 1246, "embedded": 1184, "missing": 62}
    assert by_table["attractions"] == {"table": "attractions", "label": "Địa điểm", "total": 312, "embedded": 312, "missing": 0}
    assert body["total_missing"] == 62


@pytest.mark.asyncio
async def test_summary_never_queries_room_prices(client, admin_override, monkeypatch):
    """`room_prices` has no `embedding` column and must never appear in any
    count here (plan's grep-checked success criterion)."""
    fake_client = _FakeClient({"hotels": _hotels(1, 0), "rooms": _rooms(1, 0), "attractions": _attractions(1, 0)})
    monkeypatch.setattr(embedding_module, "get_supabase_client", lambda: fake_client)

    await client.get("/api/v1/admin/embedding/summary")

    assert "room_prices" not in fake_client.table_calls


# ---------------------------------------------------------------------------
# GET /api/v1/admin/embedding/missing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_rooms_carries_hotel_name_from_join(client, admin_override, monkeypatch):
    rows = [
        {"id": "r1", "name": "Deluxe King", "updated_at": "2026-08-24T08:00:00Z", "embedding": None, "hotels": {"name": "Silk Path Hà Nội"}}
    ]
    fake_client = _FakeClient({"rooms": rows})
    monkeypatch.setattr(embedding_module, "get_supabase_client", lambda: fake_client)

    response = await client.get("/api/v1/admin/embedding/missing", params={"table": "rooms", "limit": 20})

    assert response.status_code == 200
    items = response.json()["items"]
    assert items == [{"id": "r1", "name": "Deluxe King", "hotel_name": "Silk Path Hà Nội", "updated_at": "2026-08-24T08:00:00Z"}]
    # `updated_at` is nullable; postgrest defaults DESC to NULLS FIRST, which
    # would let null-updated_at rows crowd out the genuine most-recent ones.
    query = fake_client.queries["rooms"][0]
    assert query.order_calls == [("updated_at", {"desc": True, "nullsfirst": False})]


@pytest.mark.asyncio
async def test_missing_hotels_has_no_hotel_name(client, admin_override, monkeypatch):
    rows = [{"id": "h1", "name": "Vinpearl Resort", "updated_at": "2026-08-24T08:00:00Z", "embedding": None}]
    fake_client = _FakeClient({"hotels": rows})
    monkeypatch.setattr(embedding_module, "get_supabase_client", lambda: fake_client)

    response = await client.get("/api/v1/admin/embedding/missing", params={"table": "hotels"})

    assert response.json()["items"][0]["hotel_name"] is None
    query = fake_client.queries["hotels"][0]
    assert query.order_calls == [("updated_at", {"desc": True, "nullsfirst": False})]


@pytest.mark.asyncio
async def test_missing_rejects_unknown_table(client, admin_override):
    response = await client.get("/api/v1/admin/embedding/missing", params={"table": "room_prices"})

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# POST /api/v1/admin/hotels/reembed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reembed_clears_hotel_embedding_and_reports_airflow_unavailable(client, admin_override, no_audit, monkeypatch):
    fake_client = _FakeClient({"hotels": [{"id": "h1", "embedding": [0.1]}, {"id": "h2", "embedding": [0.1]}]})
    monkeypatch.setattr(embedding_module, "get_supabase_client", lambda: fake_client)

    response = await client.post("/api/v1/admin/hotels/reembed", json={"hotel_ids": ["h1", "h2"]})

    assert response.status_code == 200
    body = response.json()
    assert body == {"cleared_hotels": 2, "cleared_rooms": 0, "dag_run_id": None, "queued": False, "detail": "airflow_unavailable"}
    assert fake_client._tables["hotels"][0]["embedding"] is None
    assert fake_client._tables["hotels"][1]["embedding"] is None
    assert "rooms" not in fake_client.table_calls
    # One audit row per hotel, not one row for the whole batch -- keeps
    # `admin_audit_log`'s (entity_type, entity_id) index answerable per hotel.
    assert len(no_audit) == 2
    assert {call["entity_id"] for call in no_audit} == {"h1", "h2"}
    assert all(call["action"] == "embedding.reembed" for call in no_audit)
    assert all(call["after"] == {"hotel_ids": ["h1", "h2"], "cleared_hotels": 2, "cleared_rooms": 0} for call in no_audit)
    # `returning="minimal"` -- a bulk clear has no reason to pull every
    # touched row's full columns back just to discard them; `count="exact"`
    # still reports the affected-row count independent of `returning`.
    hotels_update = fake_client.queries["hotels"][0]
    assert hotels_update.update_kwargs == {"count": "exact", "returning": "minimal"}


@pytest.mark.asyncio
async def test_reembed_with_include_rooms_also_clears_hotel_rooms(client, admin_override, no_audit, monkeypatch):
    fake_client = _FakeClient(
        {
            "hotels": [{"id": "h1", "embedding": [0.1]}],
            "rooms": [{"id": "r1", "hotel_id": "h1", "embedding": [0.1]}, {"id": "r2", "hotel_id": "other", "embedding": [0.1]}],
        }
    )
    monkeypatch.setattr(embedding_module, "get_supabase_client", lambda: fake_client)

    response = await client.post("/api/v1/admin/hotels/reembed", json={"hotel_ids": ["h1"], "include_rooms": True})

    assert response.status_code == 200
    assert response.json()["cleared_rooms"] == 1
    assert fake_client._tables["rooms"][0]["embedding"] is None
    assert fake_client._tables["rooms"][1]["embedding"] == [0.1]


@pytest.mark.asyncio
async def test_reembed_rejects_empty_hotel_ids(client, admin_override):
    response = await client.post("/api/v1/admin/hotels/reembed", json={"hotel_ids": []})

    assert response.status_code == 422
