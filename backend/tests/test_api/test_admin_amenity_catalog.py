"""Tests for admin -- Danh mục tiện ích & tiện nghi (phase-18-amenity-catalog.md),
src/api/admin/amenity_catalog.py. Same generic in-memory postgrest fake
pattern as test_admin_hotels.py/test_admin_rooms.py, extended with
`.is_()`/`.not_.is_()` (retired_at null-checks) and `.upsert()` (discovery
writes via services/amenity_catalog.py's `discover_and_store_amenities`).

Two call sites need the SAME fake Supabase client: the router
(src.api.admin.amenity_catalog) for its own direct table reads/writes, and
the service module (src.services.amenity_catalog) for `score_against_catalog`/
`draft_new_amenities`/`clear_all_approved_amenities_cache`'s cache-adjacent
reads -- both are monkeypatched to the one instance so a row written via one
path is visible to the other, exactly like the real Supabase connection is
shared.
"""

from __future__ import annotations

import pytest

from src.api.admin import amenity_catalog as router_module
from src.auth import AdminUser, require_admin
from src.main import app
from src.services import amenity_catalog as service_module


class _Response:
    def __init__(self, data, count=None):
        self.data = data
        self.count = count


class _NotProxy:
    def __init__(self, query: "_FakeQuery"):
        self._query = query

    def is_(self, field, _value):
        self._query._not_null.append(field)
        return self._query


class _FakeQuery:
    def __init__(self, rows: list[dict]):
        self._rows = rows
        self._eq: list[tuple[str, object]] = []
        self._in: list[tuple[str, list]] = []
        self._is_null: list[str] = []
        self._not_null: list[str] = []
        self._or: str | None = None
        self._start: int | None = None
        self._end: int | None = None
        self.update_payload: dict | None = None
        self._inserted: list[dict] | None = None
        self._deleting = False
        self._upserted: list[dict] | None = None

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, field, value):
        self._eq.append((field, value))
        return self

    def in_(self, field, values):
        self._in.append((field, list(values)))
        return self

    def is_(self, field, _value):
        self._is_null.append(field)
        return self

    @property
    def not_(self):
        return _NotProxy(self)

    def or_(self, expr):
        self._or = expr
        return self

    def order(self, *_args, **_kwargs):
        return self

    def range(self, start, end):
        self._start, self._end = start, end
        return self

    def limit(self, n):
        if self._start is None:
            self._start, self._end = 0, n - 1
        return self

    def update(self, payload):
        self.update_payload = payload
        return self

    def insert(self, payload):
        row = {**payload, "id": payload.get("id") or f"generated-{len(self._rows)}"}
        self._rows.append(row)
        self._inserted = [row]
        return self

    def upsert(self, rows, on_conflict=None):
        del on_conflict
        by_id = {row["id"]: row for row in self._rows}
        for incoming in rows:
            existing = by_id.get(incoming["id"])
            if existing is not None:
                existing.update(incoming)
            else:
                self._rows.append(dict(incoming))
                by_id[incoming["id"]] = incoming
        self._upserted = rows
        return self

    def delete(self):
        self._deleting = True
        return self

    def _matches(self, row) -> bool:
        for field, value in self._eq:
            if row.get(field) != value:
                return False
        for field, values in self._in:
            if row.get(field) not in values:
                return False
        for field in self._is_null:
            if row.get(field) is not None:
                return False
        for field in self._not_null:
            if row.get(field) is None:
                return False
        return True

    def execute(self):
        if self._upserted is not None:
            return _Response(self._upserted, count=len(self._upserted))
        if self._inserted is not None:
            return _Response(self._inserted, count=len(self._inserted))
        matched = [row for row in self._rows if self._matches(row)]
        if self.update_payload is not None:
            for row in matched:
                row.update(self.update_payload)
            return _Response(matched, count=len(matched))
        if self._deleting:
            for row in matched:
                self._rows.remove(row)
            return _Response(matched, count=len(matched))
        rows = matched
        total = len(matched)
        if self._start is not None:
            rows = rows[self._start : self._end + 1]
        return _Response(rows, count=total)


class _FakeClient:
    def __init__(self, tables: dict[str, list[dict]]):
        self._tables = tables

    def table(self, name):
        return _FakeQuery(self._tables.setdefault(name, []))


def _entry(id_: str, label_vi: str, label_en: str, *, scope="hotel", category="general", keywords=None) -> dict:
    return {
        "id": id_, "label_vi": label_vi, "label_en": label_en, "scope": scope, "category": category,
        "icon_key": None, "match_keywords": keywords or [label_vi.lower(), label_en.lower()],
        "parent_id": None, "is_approved": True, "retired_at": None,
    }


@pytest.fixture
def admin_override():
    app.dependency_overrides[require_admin] = lambda: AdminUser(id="admin-1", email="admin@vsftrip.vn")
    yield
    app.dependency_overrides.pop(require_admin, None)


@pytest.fixture
def no_audit(monkeypatch):
    calls: list[dict] = []
    monkeypatch.setattr(router_module, "write_audit", lambda actor, **kwargs: calls.append({"actor": actor, **kwargs}))
    return calls


@pytest.fixture
def fake_client(monkeypatch):
    client = _FakeClient({"amenity_catalog": [], "admin_amenity_usage": []})
    monkeypatch.setattr(router_module, "get_supabase_client", lambda: client)
    monkeypatch.setattr(service_module, "get_supabase_client", lambda: client)
    monkeypatch.setattr(service_module, "clear_all_approved_amenities_cache", lambda: None)
    return client


BASE = "/api/v1/admin/amenity-catalog"


# ---------------------------------------------------------------------- #
# GET list
# ---------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_list_filters_by_status(client, fake_client, admin_override):
    fake_client._tables["amenity_catalog"] = [
        _entry("wifi", "Wi-Fi", "Wi-Fi"),
        {**_entry("gym", "Phòng gym", "Gym"), "is_approved": False},
        {**_entry("old_spa", "Spa cũ", "Old spa"), "retired_at": "2026-08-20T00:00:00Z"},
    ]

    approved = await client.get(f"{BASE}?status=approved")
    assert [item["id"] for item in approved.json()["items"]] == ["wifi"]

    pending = await client.get(f"{BASE}?status=pending")
    assert [item["id"] for item in pending.json()["items"]] == ["gym"]
    assert pending.json()["pending_count"] == 1

    retired = await client.get(f"{BASE}?status=retired")
    assert [item["id"] for item in retired.json()["items"]] == ["old_spa"]


@pytest.mark.asyncio
async def test_list_includes_usage_and_child_counts(client, fake_client, admin_override):
    fake_client._tables["amenity_catalog"] = [
        _entry("parking", "Bãi đỗ xe", "Parking"),
        {**_entry("free_parking", "Bãi đỗ xe miễn phí", "Free parking"), "parent_id": "parking"},
    ]
    fake_client._tables["admin_amenity_usage"] = [{"amenity_id": "free_parking", "hotel_count": 5, "room_count": 0}]

    response = await client.get(f"{BASE}?q=parking")
    items = {item["id"]: item for item in response.json()["items"]}
    assert items["parking"]["hotel_count"] == 0
    assert items["parking"]["child_count"] == 1
    assert items["free_parking"]["hotel_count"] == 5
    assert items["free_parking"]["child_count"] == 0


@pytest.mark.asyncio
async def test_get_amenity_returns_single_row(client, fake_client, admin_override):
    fake_client._tables["amenity_catalog"] = [_entry("wifi", "Wi-Fi", "Wi-Fi")]

    response = await client.get(f"{BASE}/wifi")
    assert response.status_code == 200
    assert response.json()["id"] == "wifi"
    assert response.json()["label_vi"] == "Wi-Fi"


@pytest.mark.asyncio
async def test_get_amenity_404s_for_unknown_id(client, fake_client, admin_override):
    fake_client._tables["amenity_catalog"] = []

    response = await client.get(f"{BASE}/does-not-exist")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_list_sorts_by_usage_across_pages(client, fake_client, admin_override):
    """Sorting by usage must reflect every matched row, not just whatever
    page happened to already be loaded -- the bug this replaced: client-side
    sort only ever reordered the current page's 25 rows."""
    fake_client._tables["amenity_catalog"] = [
        _entry("mid", "Giữa", "Mid"),
        _entry("low", "Thấp", "Low"),
        _entry("high", "Cao", "High"),
    ]
    fake_client._tables["admin_amenity_usage"] = [
        {"amenity_id": "mid", "hotel_count": 5, "room_count": 0},
        {"amenity_id": "high", "hotel_count": 10, "room_count": 5},
        # "low" has no row in the usage view at all -- must default to 0,
        # not be dropped or crash the sort.
    ]

    page1 = await client.get(f"{BASE}?sort=usage&direction=asc&page=1&page_size=2")
    body1 = page1.json()
    assert [item["id"] for item in body1["items"]] == ["low", "mid"]
    assert body1["total"] == 3

    page2 = await client.get(f"{BASE}?sort=usage&direction=asc&page=2&page_size=2")
    assert [item["id"] for item in page2.json()["items"]] == ["high"]

    desc = await client.get(f"{BASE}?sort=usage&direction=desc&page=1&page_size=3")
    assert [item["id"] for item in desc.json()["items"]] == ["high", "mid", "low"]


@pytest.mark.asyncio
async def test_list_sorts_by_status(client, fake_client, admin_override):
    fake_client._tables["amenity_catalog"] = [
        _entry("approved_one", "Đã duyệt", "Approved"),
        {**_entry("pending_one", "Chờ duyệt", "Pending"), "is_approved": False},
        {**_entry("retired_one", "Ngừng dùng", "Retired"), "retired_at": "2026-08-20T00:00:00Z"},
    ]

    asc = await client.get(f"{BASE}?sort=status&direction=asc")
    assert [item["id"] for item in asc.json()["items"]] == ["pending_one", "approved_one", "retired_one"]

    desc = await client.get(f"{BASE}?sort=status&direction=desc")
    assert [item["id"] for item in desc.json()["items"]] == ["retired_one", "approved_one", "pending_one"]


# ---------------------------------------------------------------------- #
# check-duplicate / draft
# ---------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_check_duplicate_buckets_by_score(client, fake_client, admin_override):
    fake_client._tables["amenity_catalog"] = [_entry("swimming_pool", "Hồ bơi", "Swimming pool", category="wellness")]

    response = await client.post(f"{BASE}/check-duplicate", json={"text": "Hồ bơi, Xông hơi", "scope": "hotel"})
    body = response.json()
    assert body["parsed"] == ["Hồ bơi", "Xông hơi"]
    assert [m["name"] for m in body["exact"]] == ["Hồ bơi"]
    assert body["exact"][0]["closest"]["id"] == "swimming_pool"
    assert [m["name"] for m in body["flagged"]] == []
    assert body["clear"] == ["Xông hơi"]


@pytest.mark.asyncio
async def test_check_duplicate_parses_commas_and_newlines_and_dedupes(client, fake_client, admin_override):
    response = await client.post(f"{BASE}/check-duplicate", json={"text": "Xông hơi,\nBồn sục, Xông hơi", "scope": "hotel"})
    assert response.json()["parsed"] == ["Xông hơi", "Bồn sục"]


@pytest.mark.asyncio
async def test_draft_skips_exact_matches_and_merges_same_batch_duplicates(client, fake_client, admin_override, no_audit, monkeypatch):
    fake_client._tables["amenity_catalog"] = [_entry("swimming_pool", "Hồ bơi", "Swimming pool", category="wellness")]

    class _Response:
        # `_discovery_candidates` slugs each raw Vietnamese label into its
        # own source id -- the model must echo that same id back per its
        # "use only submitted ids" instruction. Both results share label_en
        # "Dry Sauna" on purpose: services/amenity_catalog.py's discovery
        # loop treats a same-label_en candidate seen later in the same batch
        # as an alias of the one just created (comparison_entries grows as
        # rows are produced), not a second row -- this is what actually
        # prevents same-batch catalog duplicates, and is what's under test
        # here (not a `_2`-suffix collision, which same-label detection
        # pre-empts before `_unique_canonical_id` is ever reached).
        content = (
            '{"amenities":['
            '{"id":"xong_hoi_kho","is_amenity":true,"label_vi":"Xông hơi khô","label_en":"Dry Sauna","scope":"hotel","category":"wellness","icon_key":null,"match_keywords":["sauna"],"parent_id":null},'
            '{"id":"xong_hoi_uot","is_amenity":true,"label_vi":"Xông hơi ướt","label_en":"Dry Sauna","scope":"hotel","category":"wellness","icon_key":null,"match_keywords":["steam"],"parent_id":null}'
            ']}'
        )

    class _FastModel:
        def invoke(self, _messages):
            return _Response()

    monkeypatch.setattr(service_module, "get_fast_llm", lambda **_: _FastModel())

    response = await client.post(
        f"{BASE}/draft",
        json={"names": ["Hồ bơi", "Xông hơi khô", "Xông hơi ướt"], "scope": "hotel"},
    )
    body = response.json()
    assert body["skipped_exact"] == ["Hồ bơi"]
    assert [item["id"] for item in body["items"]] == ["dry_sauna"]
    # The merge alias-path (_existing_catalog_row) keeps the first row's own
    # keywords and adds each subsequent candidate's raw source label as an
    # alias -- it does not re-run the second candidate's own match_keywords
    # ("steam") into the merged row.
    assert set(body["items"][0]["match_keywords"]) >= {"sauna", "xông hơi ướt"}
    assert body["items"][0]["is_approved"] is False
    assert len(no_audit) == 1
    assert no_audit[0]["action"] == "amenity.draft"


@pytest.mark.asyncio
async def test_draft_creates_acknowledged_exact_match(client, fake_client, admin_override, monkeypatch):
    """An admin who's certain an exact-scored name isn't really a duplicate
    (e.g. a false positive from a single shared generic keyword) can now
    override it via `acknowledge`, same as the flagged band already allows --
    it's no longer an unconditional block. Note what "override" actually
    buys here: acknowledging lets the name reach `draft_new_amenities`, but
    that pipeline does its own matching against the live catalog, so a name
    that's a genuine literal duplicate (this one) still resolves back onto
    the existing row as an alias rather than minting a second row for the
    same thing -- the override unblocks *processing*, it doesn't force a
    literal duplicate insert. A name the LLM judges as actually distinct
    would get its own new row, same as the flagged-band test above."""
    fake_client._tables["amenity_catalog"] = [_entry("swimming_pool", "Hồ bơi", "Swimming pool", category="wellness")]

    class _Response:
        # `_discovery_candidates` slugs "Hồ bơi" deterministically to
        # "ho_boi" -- the model must echo that same source id back.
        content = '{"amenities":[{"id":"ho_boi","is_amenity":true,"label_vi":"Hồ bơi","label_en":"Pool 2","scope":"hotel","category":"wellness","icon_key":null,"match_keywords":["pool"],"parent_id":null}]}'

    class _FastModel:
        def invoke(self, _messages):
            return _Response()

    monkeypatch.setattr(service_module, "get_fast_llm", lambda **_: _FastModel())

    response = await client.post(f"{BASE}/draft", json={"names": ["Hồ bơi"], "scope": "hotel", "acknowledge": ["Hồ bơi"]})
    body = response.json()
    assert body["skipped_exact"] == []
    assert [item["id"] for item in body["items"]] == ["swimming_pool"]


@pytest.mark.asyncio
async def test_draft_skips_unacknowledged_flagged_names_without_erroring(client, fake_client, admin_override, monkeypatch):
    fake_client._tables["amenity_catalog"] = [_entry("swimming_pool", "Hồ bơi", "Swimming pool", category="wellness")]

    def fail_if_called(*_a, **_kw):
        raise AssertionError("LLM should not be called for a name skipped as unacknowledged")

    monkeypatch.setattr(service_module, "get_fast_llm", fail_if_called)

    # "Swimming" alone scores ~0.76 against "Hồ bơi"/"Swimming pool" --
    # inside the flagged band (0.55-0.85), not exact.
    response = await client.post(f"{BASE}/draft", json={"names": ["Swimming"], "scope": "hotel", "acknowledge": []})
    body = response.json()
    assert body["items"] == []
    assert body["skipped_duplicate"] == ["Swimming"]


@pytest.mark.asyncio
async def test_draft_creates_acknowledged_flagged_name(client, fake_client, admin_override, monkeypatch):
    fake_client._tables["amenity_catalog"] = [_entry("swimming_pool", "Hồ bơi", "Swimming pool", category="wellness")]

    class _Response:
        content = '{"amenities":[{"id":"swimming","is_amenity":true,"label_vi":"Swimming","label_en":"Swimming","scope":"hotel","category":"wellness","icon_key":null,"match_keywords":["swimming"],"parent_id":null}]}'

    class _FastModel:
        def invoke(self, _messages):
            return _Response()

    monkeypatch.setattr(service_module, "get_fast_llm", lambda **_: _FastModel())

    response = await client.post(f"{BASE}/draft", json={"names": ["Swimming"], "scope": "hotel", "acknowledge": ["Swimming"]})
    body = response.json()
    assert body["skipped_duplicate"] == []
    assert [item["id"] for item in body["items"]] == ["swimming"]


# ---------------------------------------------------------------------- #
# PATCH (edit)
# ---------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_update_ignores_id_and_status_fields(client, fake_client, admin_override, no_audit):
    fake_client._tables["amenity_catalog"] = [_entry("wifi", "Wi-Fi", "Wi-Fi", category="connectivity")]

    response = await client.patch(f"{BASE}/wifi", json={"label_vi": "Wifi miễn phí", "id": "renamed", "is_approved": False})
    assert response.status_code == 200
    assert response.json()["changed_fields"] == ["label_vi"]
    row = fake_client._tables["amenity_catalog"][0]
    assert row["id"] == "wifi"
    assert row["is_approved"] is True
    assert row["label_vi"] == "Wifi miễn phí"


@pytest.mark.asyncio
async def test_update_rejects_multi_hop_parent_cycle(client, fake_client, admin_override):
    fake_client._tables["amenity_catalog"] = [
        _entry("a", "A", "A"),
        {**_entry("b", "B", "B"), "parent_id": "a"},
        {**_entry("c", "C", "C"), "parent_id": "b"},
    ]

    # a -> parent c would close a -> c -> b -> a
    response = await client.patch(f"{BASE}/a", json={"parent_id": "c"})
    assert response.status_code == 422
    assert response.json()["detail"] == "parent_id_cycle"


@pytest.mark.asyncio
async def test_update_keyword_reorder_is_not_a_change(client, fake_client, admin_override, no_audit):
    fake_client._tables["amenity_catalog"] = [_entry("wifi", "Wi-Fi", "Wi-Fi", keywords=["a", "b"])]
    response = await client.patch(f"{BASE}/wifi", json={"match_keywords": ["b", "a"]})
    assert response.json()["changed_fields"] == []
    assert no_audit == []


# ---------------------------------------------------------------------- #
# approve / bulk-approve / delete
# ---------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_approve_pending_amenity(client, fake_client, admin_override, no_audit):
    fake_client._tables["amenity_catalog"] = [{**_entry("gym", "Phòng gym", "Gym"), "is_approved": False}]
    response = await client.post(f"{BASE}/gym/approve")
    assert response.json() == {"id": "gym", "is_approved": True}
    assert fake_client._tables["amenity_catalog"][0]["is_approved"] is True
    assert no_audit[0]["action"] == "amenity.approve"


@pytest.mark.asyncio
async def test_bulk_approve_only_touches_pending_ids(client, fake_client, admin_override, no_audit):
    fake_client._tables["amenity_catalog"] = [
        {**_entry("gym", "Phòng gym", "Gym"), "is_approved": False},
        _entry("wifi", "Wi-Fi", "Wi-Fi"),
    ]
    response = await client.post(f"{BASE}/bulk-approve", json={"ids": ["gym", "wifi"]})
    assert response.json() == {"approved": 1}
    assert len(no_audit) == 1


@pytest.mark.asyncio
async def test_delete_pending_amenity_succeeds(client, fake_client, admin_override, no_audit):
    fake_client._tables["amenity_catalog"] = [{**_entry("gym", "Phòng gym", "Gym"), "is_approved": False}]
    response = await client.delete(f"{BASE}/gym")
    assert response.status_code == 204
    assert fake_client._tables["amenity_catalog"] == []
    assert no_audit[0]["action"] == "amenity.delete"


@pytest.mark.asyncio
async def test_delete_approved_amenity_is_always_409(client, fake_client, admin_override, no_audit):
    fake_client._tables["amenity_catalog"] = [_entry("wifi", "Wi-Fi", "Wi-Fi")]
    response = await client.delete(f"{BASE}/wifi")
    assert response.status_code == 409
    assert response.json()["detail"] == "amenity_approved_use_retire_instead"
    assert fake_client._tables["amenity_catalog"]
    assert no_audit == []


# ---------------------------------------------------------------------- #
# retire / reactivate
# ---------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_retire_blocked_by_direct_usage(client, fake_client, admin_override, no_audit):
    fake_client._tables["amenity_catalog"] = [_entry("wifi", "Wi-Fi", "Wi-Fi")]
    fake_client._tables["admin_amenity_usage"] = [{"amenity_id": "wifi", "hotel_count": 3, "room_count": 1}]

    response = await client.patch(f"{BASE}/wifi/retire")
    assert response.status_code == 409
    assert response.json() == {"detail": "amenity_in_use", "hotel_count": 3, "room_count": 1, "child_count": 0}
    assert fake_client._tables["amenity_catalog"][0]["retired_at"] is None
    assert no_audit == []


@pytest.mark.asyncio
async def test_retire_blocked_by_live_children_even_with_zero_direct_usage(client, fake_client, admin_override, no_audit):
    """G12: `parking` itself may have zero direct hotel/room usage while its
    children carry all of it -- the usage view alone would miss this."""
    fake_client._tables["amenity_catalog"] = [
        _entry("parking", "Bãi đỗ xe", "Parking"),
        {**_entry("free_parking", "Bãi đỗ xe miễn phí", "Free parking"), "parent_id": "parking"},
    ]
    fake_client._tables["admin_amenity_usage"] = [{"amenity_id": "free_parking", "hotel_count": 40, "room_count": 0}]

    response = await client.patch(f"{BASE}/parking/retire")
    assert response.status_code == 409
    body = response.json()
    assert body["detail"] == "amenity_has_active_children"
    assert body["child_count"] == 1
    assert body["children"][0]["id"] == "free_parking"
    assert no_audit == []


@pytest.mark.asyncio
async def test_retire_succeeds_at_zero_usage_and_zero_children(client, fake_client, admin_override, no_audit):
    fake_client._tables["amenity_catalog"] = [_entry("rooftop_bar", "Bar trên tầng thượng", "Rooftop bar", category="food")]

    response = await client.patch(f"{BASE}/rooftop_bar/retire")
    assert response.status_code == 200
    assert response.json()["retired_at"] is not None
    assert fake_client._tables["amenity_catalog"][0]["retired_at"] is not None
    assert fake_client._tables["amenity_catalog"][0]["is_approved"] is True  # G8/G9: retire never touches is_approved
    assert no_audit[0]["action"] == "amenity.retire"


@pytest.mark.asyncio
async def test_retire_pending_amenity_is_rejected(client, fake_client, admin_override):
    fake_client._tables["amenity_catalog"] = [{**_entry("gym", "Phòng gym", "Gym"), "is_approved": False}]
    response = await client.patch(f"{BASE}/gym/retire")
    assert response.status_code == 409
    assert response.json()["detail"] == "amenity_not_approved"


@pytest.mark.asyncio
async def test_reactivate_clears_retired_at(client, fake_client, admin_override, no_audit):
    fake_client._tables["amenity_catalog"] = [{**_entry("rooftop_bar", "Bar", "Rooftop bar"), "retired_at": "2026-08-20T00:00:00Z"}]
    response = await client.post(f"{BASE}/rooftop_bar/reactivate")
    assert response.json() == {"id": "rooftop_bar", "retired_at": None}
    assert fake_client._tables["amenity_catalog"][0]["retired_at"] is None
    assert no_audit[0]["action"] == "amenity.reactivate"


# ---------------------------------------------------------------------- #
# Regression guard: is_approved(false)+retired_at(null) rows are exactly
# what query_approved_amenities() must exclude/include after the phase-18
# retired_at filter change.
# ---------------------------------------------------------------------- #


def test_query_approved_amenities_excludes_retired_rows(monkeypatch):
    client = _FakeClient({"amenity_catalog": [
        _entry("wifi", "Wi-Fi", "Wi-Fi"),
        {**_entry("rooftop_bar", "Bar", "Rooftop bar"), "retired_at": "2026-08-20T00:00:00Z"},
    ]})
    monkeypatch.setattr(service_module, "get_supabase_client", lambda: client)

    entries = service_module.query_approved_amenities()

    assert [entry.id for entry in entries] == ["wifi"]
