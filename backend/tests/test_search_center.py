"""Phase 8 (260812-0927-langgraph-orchestration-state-patch-and-interrupts):
`services/search_center.py` — deterministic center resolution for hotel
radius search. No LLM/model involvement anywhere (doc §20: "Do not let GPT
calculate geographic distance") -- coordinates only ever come from a real
`attractions` row or an already-known hotel location.
"""

from __future__ import annotations

import src.services.search_center as search_center_module
from src.services.search_center import extract_named_place, find_attraction_by_name, resolve_center


class _FakeQuery:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def limit(self, _n: int) -> _FakeQuery:
        return self

    def execute(self) -> _FakeResult:
        return _FakeResult(self._rows)


class _FakeResult:
    def __init__(self, data: list[dict]) -> None:
        self.data = data


class _FakeTable:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def select(self, *_args, **_kwargs) -> _FakeTable:
        return self

    def eq(self, column: str, value) -> _FakeTable:
        return _FakeTable([row for row in self._rows if row.get(column) == value])

    def ilike(self, column: str, pattern: str) -> _FakeQuery:
        needle = pattern.strip("%").casefold()
        return _FakeQuery([row for row in self._rows if needle in str(row.get(column, "")).casefold()])


class _FakeSupabaseClient:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def table(self, _name: str) -> _FakeTable:
        return _FakeTable(self._rows)


_ATTRACTIONS = [
    {"id": "attr-1", "destination_id": "dest-1", "name": "Bà Nà Hills", "coordinates": "15.9977,107.9857"},
    {"id": "attr-2", "destination_id": "dest-2", "name": "Chợ Bến Thành", "coordinates": "10.7725,106.698"},
]


# --- extract_named_place -----------------------------------------------------


def test_extract_named_place_after_tu_preposition():
    assert extract_named_place("Tìm khách sạn trong bán kính 3km từ Bà Nà Hills.") == "Bà Nà Hills"


def test_extract_named_place_before_radius_clause():
    assert extract_named_place("Tìm khách sạn cách Bà Nà Hills 3km") == "Bà Nà Hills"


def test_extract_named_place_returns_none_without_a_preposition():
    assert extract_named_place("Tìm khách sạn trong bán kính 3km, có gym và hồ bơi.") is None


# --- find_attraction_by_name --------------------------------------------------


def test_find_attraction_by_name_matches_case_insensitively(monkeypatch):
    monkeypatch.setattr(search_center_module, "get_supabase_client", lambda: _FakeSupabaseClient(_ATTRACTIONS))

    coordinates = find_attraction_by_name("bà nà hills", "dest-1")

    assert coordinates == (15.9977, 107.9857)


def test_find_attraction_by_name_scoped_to_destination(monkeypatch):
    monkeypatch.setattr(search_center_module, "get_supabase_client", lambda: _FakeSupabaseClient(_ATTRACTIONS))

    # "Bà Nà Hills" only exists under dest-1 -- searching dest-2 must not match.
    assert find_attraction_by_name("Bà Nà Hills", "dest-2") is None


def test_find_attraction_by_name_no_match_returns_none(monkeypatch):
    monkeypatch.setattr(search_center_module, "get_supabase_client", lambda: _FakeSupabaseClient(_ATTRACTIONS))

    assert find_attraction_by_name("Núi Bà Đen", "dest-1") is None


# --- resolve_center: the three-way priority order -----------------------------


def test_resolve_center_prefers_selected_hotel_over_everything():
    resolution = resolve_center(
        destination_id="dest-1", named_place="Bà Nà Hills", selected_hotel_coordinates=(16.0, 108.2)
    )

    assert resolution.source == "selected_hotel"
    assert (resolution.latitude, resolution.longitude) == (16.0, 108.2)
    assert resolution.resolved


def test_resolve_center_falls_back_to_named_poi(monkeypatch):
    monkeypatch.setattr(search_center_module, "get_supabase_client", lambda: _FakeSupabaseClient(_ATTRACTIONS))

    resolution = resolve_center(destination_id="dest-1", named_place="Bà Nà Hills", selected_hotel_coordinates=None)

    assert resolution.source == "poi"
    assert resolution.resolved
    assert (resolution.latitude, resolution.longitude) == (15.9977, 107.9857)


def test_resolve_center_unresolved_when_neither_is_known(monkeypatch):
    monkeypatch.setattr(search_center_module, "get_supabase_client", lambda: _FakeSupabaseClient(_ATTRACTIONS))

    resolution = resolve_center(destination_id="dest-1", named_place=None, selected_hotel_coordinates=None)

    assert resolution.source == "unresolved"
    assert not resolution.resolved


def test_resolve_center_unresolved_when_named_place_has_no_db_match(monkeypatch):
    monkeypatch.setattr(search_center_module, "get_supabase_client", lambda: _FakeSupabaseClient(_ATTRACTIONS))

    resolution = resolve_center(
        destination_id="dest-1", named_place="một nơi không tồn tại", selected_hotel_coordinates=None
    )

    assert resolution.source == "unresolved"
    assert not resolution.resolved
