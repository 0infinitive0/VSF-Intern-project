from types import SimpleNamespace

from src.services import amenity_catalog


class _Query:
    def __init__(self, rows):
        self.rows = rows
        self.filters = []
        self.requested_ids = None
        self.limit_value = None

    def select(self, fields):
        self.fields = fields
        return self

    def eq(self, field, value):
        self.filters.append((field, value))
        return self

    def in_(self, field, values):
        self.requested_ids = (field, values)
        return self

    def limit(self, value):
        self.limit_value = value
        return self

    def execute(self):
        return SimpleNamespace(data=self.rows)


class _Client:
    def __init__(self, rows):
        self.rows = rows
        self.query = None

    def table(self, name):
        assert name == "amenity_catalog"
        self.query = _Query(self.rows)
        return self.query


def test_query_approved_amenities_filters_by_sanitized_ids(monkeypatch):
    client = _Client(
        [
            {"id": "parking", "label_vi": "Bãi đỗ xe", "label_en": "Parking", "scope": "hotel", "category": "transport", "icon_key": "local_parking", "match_keywords": ["parking", "bãi đỗ xe"]},
            {"id": "wifi", "label_vi": "Wi-Fi", "label_en": "Wi-Fi", "scope": "both", "category": "connectivity", "icon_key": "wifi", "match_keywords": ["wifi"]},
        ]
    )
    monkeypatch.setattr(amenity_catalog, "get_supabase_client", lambda: client)

    entries = amenity_catalog.query_approved_amenities(
        ["parking", "DROP TABLE", "PARKING", "wifi"]
    )

    assert [(entry.id, entry.label) for entry in entries] == [
        ("parking", "Bãi đỗ xe"),
        ("wifi", "Wi-Fi"),
    ]
    assert client.query.filters == [("is_approved", True)]
    assert client.query.requested_ids == ("id", ["parking", "wifi"])
    assert client.query.limit_value == 100


def test_query_approved_amenities_fails_closed_when_catalog_is_unavailable(monkeypatch):
    def unavailable_client():
        raise RuntimeError("relation does not exist")

    monkeypatch.setattr(amenity_catalog, "get_supabase_client", unavailable_client)

    assert amenity_catalog.query_approved_amenities() == []


def test_query_approved_amenities_reads_every_catalog_page(monkeypatch):
    rows = [
        {
            "id": f"entry_{index}", "label_vi": f"Nhãn {index}", "label_en": f"Label {index}",
            "scope": "hotel", "category": "facility", "icon_key": None, "match_keywords": [f"entry {index}"],
        }
        for index in range(1_001)
    ]

    class Query:
        def __init__(self):
            self.start = 0
            self.end = -1
        def select(self, _fields): return self
        def eq(self, _field, _value): return self
        def range(self, start, end):
            self.start = start
            self.end = end
            return self
        def execute(self): return SimpleNamespace(data=rows[self.start:self.end + 1])

    class Client:
        def table(self, _name): return Query()

    monkeypatch.setattr(amenity_catalog, "get_supabase_client", lambda: Client())

    assert len(amenity_catalog.query_approved_amenities()) == 1_001


def test_query_all_approved_amenities_by_ids_batches_without_truncating(monkeypatch):
    calls = []

    def query(ids):
        calls.append(list(ids or []))
        return []

    monkeypatch.setattr(amenity_catalog, "query_approved_amenities", query)

    amenity_catalog.query_all_approved_amenities_by_ids([f"amenity_{index}" for index in range(205)])

    assert [len(batch) for batch in calls] == [100, 100, 5]
    assert calls[0][0] == "amenity_0"
    assert calls[-1][-1] == "amenity_204"


def test_discover_and_store_amenities_inserts_only_fast_model_approved_candidates(monkeypatch):
    inserted_rows = []
    captured_messages = []

    class _Response:
        content = '''{
          "amenities": [
            {"id": "spa", "is_amenity": true, "label_vi": "phòng spa", "label_en": "Spa", "scope": "hotel", "category": "wellness", "icon_key": "spa", "match_keywords": ["wellness", "phòng spa"]},
            {"id": "history", "is_amenity": false, "match_keywords": []}
          ]
        }'''

    class _FastModel:
        def invoke(self, messages):
            captured_messages.extend(messages)
            return _Response()

    class _InsertQuery:
        def insert(self, rows):
            inserted_rows.extend(rows)
            return self

        def upsert(self, rows, on_conflict):
            assert on_conflict == "id"
            inserted_rows.extend(rows)
            return self

        def execute(self):
            return SimpleNamespace(data=inserted_rows)

    class _InsertClient:
        def table(self, name):
            assert name == "amenity_catalog"
            return _InsertQuery()

    monkeypatch.setattr(amenity_catalog, "get_fast_llm", lambda **_: _FastModel())
    monkeypatch.setattr(amenity_catalog, "get_supabase_client", lambda: _InsertClient())

    entries = amenity_catalog.discover_and_store_amenities(
        [
            {"id": "spa", "label": "phòng spa"},
            {"id": "history", "label": "lịch sử"},
        ]
    )

    assert [(entry.id, entry.label) for entry in entries] == [("spa", "phòng spa")]
    assert inserted_rows == [
        {
            "id": "spa",
            "label_vi": "phòng spa",
            "label_en": "Spa",
            "scope": "hotel",
            "category": "wellness",
            "icon_key": "spa",
            "match_keywords": ["wellness", "phòng spa"],
            "is_approved": True,
        }
    ]
    assert "unknown scraped hotel amenities" in captured_messages[0].content


def test_discovery_derives_an_english_canonical_id_and_keeps_source_mapping(monkeypatch):
    class _Response:
        content = '''{"amenities":[{"id":"tien_nghi_nau_nuong_ngoai_troi","is_amenity":true,"label_vi":"Tiện nghi nấu nướng ngoài trời","label_en":"Outdoor Cooking Facilities","scope":"hotel","category":"facility","icon_key":null,"match_keywords":["outdoor cooking facilities","outdoor kitchen","tiện nghi nấu nướng ngoài trời"]}]}'''

    class _FastModel:
        def invoke(self, _messages): return _Response()

    monkeypatch.setattr(amenity_catalog, "get_fast_llm", lambda **_: _FastModel())

    entries = amenity_catalog.discover_and_store_amenities(
        [{"id": "tien_nghi_nau_nuong_ngoai_troi", "label": "Tiện nghi nấu nướng ngoài trời"}], persist=False
    )

    assert entries == [amenity_catalog.AmenityCatalogEntry(
        id="outdoor_cooking_facilities", label="Tiện nghi nấu nướng ngoài trời", label_en="Outdoor Cooking Facilities",
        scope="hotel", category="facility", icon_key=None,
        match_keywords=("outdoor cooking facilities", "outdoor kitchen", "tiện nghi nấu nướng ngoài trời"),
        source_id="tien_nghi_nau_nuong_ngoai_troi",
    )]


def test_discovery_removes_broad_outdoor_cooking_aliases(monkeypatch):
    class _Response:
        content = '''{"amenities":[{"id":"outdoor_cooking","is_amenity":true,"label_vi":"Tiện nghi nấu nướng ngoài trời","label_en":"Outdoor Cooking Facilities","scope":"hotel","category":"facility","icon_key":null,"match_keywords":["outdoor kitchen","cooking amenities","bbq","outdoor grill area"]}]}'''

    class _FastModel:
        def invoke(self, _messages): return _Response()

    monkeypatch.setattr(amenity_catalog, "get_fast_llm", lambda **_: _FastModel())

    entry = amenity_catalog.discover_and_store_amenities(
        [{"id": "outdoor_cooking", "label": "Tiện nghi nấu nướng ngoài trời"}], persist=False
    )[0]

    assert entry.match_keywords == (
        "outdoor kitchen", "outdoor grill area", "tiện nghi nấu nướng ngoài trời",
    )


def test_discovery_falls_back_to_general_for_unknown_category(monkeypatch):
    class _Response:
        content = '''{"amenities":[{"id":"wifi","is_amenity":true,"label_vi":"Wi-Fi","label_en":"Wi-Fi","scope":"hotel","category":"invented_category","icon_key":"wifi","match_keywords":["wifi"]}]}'''

    class _FastModel:
        def invoke(self, _messages): return _Response()

    monkeypatch.setattr(amenity_catalog, "get_fast_llm", lambda **_: _FastModel())

    entry = amenity_catalog.discover_and_store_amenities(
        [{"id": "wifi", "label": "Wi-Fi"}], persist=False
    )[0]

    assert entry.category == "general"


def test_discovery_accepts_spoken_languages_as_hotel_services(monkeypatch):
    class _Response:
        content = '''{"amenities":[{"id":"tieng_viet","is_amenity":true,"label_vi":"Tiếng Việt","label_en":"Vietnamese Language","scope":"hotel","category":"general","icon_key":"translate","match_keywords":["vietnamese","tiếng việt"]}]}'''

    class _FastModel:
        def invoke(self, _messages): return _Response()

    monkeypatch.setattr(amenity_catalog, "get_fast_llm", lambda **_: _FastModel())

    entry = amenity_catalog.discover_and_store_amenities(
        [{"id": "tieng_viet", "label": "Tiếng Việt"}], persist=False
    )[0]

    assert (entry.id, entry.category) == ("vietnamese_language", "language")


def test_discovery_includes_relevant_existing_catalog_entries_in_deduplication_prompt(monkeypatch):
    captured = []

    class _Response:
        content = '{"amenities":[]}'

    class _FastModel:
        def invoke(self, messages):
            captured.extend(messages)
            return _Response()

    monkeypatch.setattr(amenity_catalog, "get_fast_llm", lambda **_: _FastModel())
    amenity_catalog.discover_and_store_amenities(
        [{"id": "internet_service", "label": "Internet Service"}],
        existing_entries=[amenity_catalog.AmenityCatalogEntry(
            id="internet", label="Internet", label_en="Internet", scope="hotel", category="connectivity",
            icon_key="wifi", match_keywords=("internet", "internet access"),
        )],
        persist=False,
    )

    assert '"id": "internet"' in captured[1].content


def test_discovery_reuses_existing_id_when_model_keyword_matches_catalog(monkeypatch):
    class _Response:
        content = '''{"amenities":[{"id":"internet_service","is_amenity":true,"label_vi":"Dịch vụ Internet","label_en":"Internet Service","scope":"hotel","category":"connectivity","icon_key":"wifi","match_keywords":["wireless internet"]}]}'''

    class _FastModel:
        def invoke(self, _messages): return _Response()

    monkeypatch.setattr(amenity_catalog, "get_fast_llm", lambda **_: _FastModel())
    existing = amenity_catalog.AmenityCatalogEntry(
        id="internet", label="Internet", label_en="Internet", scope="hotel", category="connectivity",
        icon_key="wifi", match_keywords=("wireless internet", "internet access"),
    )

    entries = amenity_catalog.discover_and_store_amenities(
        [{"id": "internet_service", "label": "Internet Service"}], existing_entries=[existing], persist=False
    )

    assert entries == [amenity_catalog.AmenityCatalogEntry(
        id="internet", label="Internet", label_en="Internet", scope="hotel", category="connectivity",
        icon_key="wifi", match_keywords=("wireless internet", "internet access", "internet service"), source_id="internet_service",
    )]


def test_discovery_accepts_only_model_selected_existing_catalog_id(monkeypatch):
    class _Response:
        content = '''{"amenities":[{"id":"internet_service","existing_id":"internet","is_amenity":false}]}'''

    class _FastModel:
        def invoke(self, _messages): return _Response()

    existing = amenity_catalog.AmenityCatalogEntry(
        id="internet", label="Internet", label_en="Internet", scope="hotel", category="connectivity",
        icon_key="wifi", match_keywords=("internet",),
    )
    monkeypatch.setattr(amenity_catalog, "get_fast_llm", lambda **_: _FastModel())

    entries = amenity_catalog.discover_and_store_amenities(
        [{"id": "internet_service", "label": "Internet Service"}], existing_entries=[existing], persist=False
    )

    assert entries == [amenity_catalog.AmenityCatalogEntry(
        id="internet", label="Internet", label_en="Internet", scope="hotel", category="connectivity",
        icon_key="wifi", match_keywords=("internet", "internet service"), source_id="internet_service",
    )]


def test_existing_model_selection_persists_the_source_phrase_as_an_alias(monkeypatch):
    persisted_rows = []

    class _Response:
        content = '''{"amenities":[{"id":"indoor_slippers","existing_id":"slippers","is_amenity":false}]}'''

    class _FastModel:
        def invoke(self, _messages): return _Response()

    class _Query:
        def upsert(self, rows, on_conflict):
            assert on_conflict == "id"
            persisted_rows.extend(rows)
            return self
        def execute(self): return SimpleNamespace(data=[])

    class _Client:
        def table(self, _name): return _Query()

    existing = amenity_catalog.AmenityCatalogEntry(
        id="slippers", label="Dép lê", label_en="Slippers", scope="hotel", category="room_comfort",
        icon_key="checkroom", match_keywords=("slippers", "dép lê"),
    )
    monkeypatch.setattr(amenity_catalog, "get_fast_llm", lambda **_: _FastModel())
    monkeypatch.setattr(amenity_catalog, "get_supabase_client", lambda: _Client())

    amenity_catalog.discover_and_store_amenities(
        [{"id": "indoor_slippers", "label": "Dép đi trong nhà"}], existing_entries=[existing]
    )

    assert persisted_rows[0]["id"] == "slippers"
    assert persisted_rows[0]["match_keywords"] == ["slippers", "dép lê", "dép đi trong nhà"]


def test_discovery_merges_multiple_aliases_for_the_same_existing_catalog_id(monkeypatch):
    persisted_rows = []

    class _Response:
        content = '''{"amenities":[{"id":"indoor_slippers","existing_id":"slippers","is_amenity":false},{"id":"guest_slippers","existing_id":"slippers","is_amenity":false}]}'''

    class _FastModel:
        def invoke(self, _messages): return _Response()

    class _Query:
        def upsert(self, rows, on_conflict):
            assert on_conflict == "id"
            persisted_rows.extend(rows)
            return self
        def execute(self): return SimpleNamespace(data=[])

    class _Client:
        def table(self, _name): return _Query()

    existing = amenity_catalog.AmenityCatalogEntry(
        id="slippers", label="Dép lê", label_en="Slippers", scope="hotel", category="room_comfort",
        icon_key="checkroom", match_keywords=("slippers", "dép lê"),
    )
    monkeypatch.setattr(amenity_catalog, "get_fast_llm", lambda **_: _FastModel())
    monkeypatch.setattr(amenity_catalog, "get_supabase_client", lambda: _Client())

    amenity_catalog.discover_and_store_amenities(
        [
            {"id": "indoor_slippers", "label": "Dép đi trong nhà"},
            {"id": "guest_slippers", "label": "Dép cho khách"},
        ],
        existing_entries=[existing],
    )

    assert persisted_rows == [{
        "id": "slippers", "label_vi": "Dép lê", "label_en": "Slippers", "scope": "hotel",
        "category": "room_comfort", "icon_key": "checkroom",
        "match_keywords": ["slippers", "dép lê", "dép đi trong nhà", "dép cho khách"], "is_approved": True,
    }]


def test_discovery_rejects_existing_id_not_relevant_to_its_own_source_phrase(monkeypatch):
    class _Response:
        content = '''{"amenities":[{"id":"wheelchair_access","existing_id":"accessible_facilities","is_amenity":false},{"id":"extra_long_bed","existing_id":"accessible_facilities","is_amenity":false}]}'''

    class _FastModel:
        def invoke(self, _messages): return _Response()

    accessible = amenity_catalog.AmenityCatalogEntry(
        id="accessible_facilities", label="Wheelchair access", label_en="Accessible facilities",
        scope="hotel", category="accessibility", icon_key="accessible", match_keywords=("wheelchair access",),
    )
    monkeypatch.setattr(amenity_catalog, "get_fast_llm", lambda **_: _FastModel())

    entries = amenity_catalog.discover_and_store_amenities(
        [
            {"id": "wheelchair_access", "label": "Wheelchair access"},
            {"id": "extra_long_bed", "label": "Extra long bed"},
        ],
        existing_entries=[accessible],
        persist=False,
    )

    assert [entry.id for entry in entries] == ["accessible_facilities"]


def test_keyword_overlap_does_not_choose_arbitrarily_when_multiple_catalog_rows_own_it():
    entries = [
        amenity_catalog.AmenityCatalogEntry(
            id="atm_on_site", label="ATM", label_en="ATM on Site", scope="hotel", category="facility",
            match_keywords=("atm",),
        ),
        amenity_catalog.AmenityCatalogEntry(
            id="cash_withdrawal", label="Rút tiền", label_en="Cash withdrawal", scope="hotel", category="facility",
            match_keywords=("atm",),
        ),
    ]

    assert amenity_catalog._keyword_duplicate(["atm"], entries, "hotel") is None


def test_scored_match_rejects_shared_keyword_without_a_clear_winner():
    entries = [
        amenity_catalog.AmenityCatalogEntry(
            id="parking", label="Chỗ đỗ xe", label_en="Parking", scope="hotel", category="transport",
            match_keywords=("car park",),
        ),
        amenity_catalog.AmenityCatalogEntry(
            id="nearby_parking", label="Bãi đỗ xe gần", label_en="Nearby Parking", scope="hotel", category="transport",
            match_keywords=("car park",),
        ),
    ]

    assert amenity_catalog._match_catalog_entry("car park", entries, "hotel") is None


def test_scored_match_accepts_one_exact_keyword_despite_a_close_fuzzy_runner():
    entries = [
        amenity_catalog.AmenityCatalogEntry(
            id="additional_toilet", label="Additional Toilet", label_en="Additional Toilet", scope="both",
            category="facility", match_keywords=("additional bathroom",),
        ),
        amenity_catalog.AmenityCatalogEntry(
            id="bathroom", label="Bathroom", label_en="Bathroom", scope="both",
            category="facility", match_keywords=("bathroom",),
        ),
    ]

    assert amenity_catalog._match_catalog_entry(
        "Additional bathroom", entries, "room", allow_cross_scope=True
    ).id == "additional_toilet"


def test_bind_amenity_rows_deduplicates_unknown_values_across_a_page(monkeypatch):
    captured_batches = []
    monkeypatch.setattr(amenity_catalog, "query_approved_amenities", lambda: [])

    def discover(candidates, *, scope, persist=True, existing_entries=()):
        captured_batches.append(list(candidates))
        return [amenity_catalog.AmenityCatalogEntry(
            id=candidate["id"], label=candidate["label"], label_en=candidate["label"], scope=scope,
            category="facility", match_keywords=(candidate["label"].lower(),), source_id=candidate["id"],
        ) for candidate in candidates]

    monkeypatch.setattr(amenity_catalog, "discover_and_store_amenities", discover)

    results = amenity_catalog.bind_amenity_rows(
        [["Unknown A", "Unknown B"], ["Unknown B", "Unknown C"]], scope="hotel"
    )

    assert captured_batches == [[
        {"id": "unknown_a", "label": "Unknown A"},
        {"id": "unknown_b", "label": "Unknown B"},
        {"id": "unknown_c", "label": "Unknown C"},
    ]]
    assert [result.ids for result in results] == [("unknown_a", "unknown_b"), ("unknown_b", "unknown_c")]


def test_bind_amenities_resolves_known_aliases_without_calling_the_model(monkeypatch):
    entries = [
        amenity_catalog.AmenityCatalogEntry(
            id="swimming_pool",
            label="Hồ bơi",
            label_en="Swimming pool",
            scope="hotel",
            category="wellness",
            icon_key="pool",
            match_keywords=("hồ bơi", "pool"),
        ),
        amenity_catalog.AmenityCatalogEntry(
            id="tv",
            label="TV",
            label_en="TV",
            scope="room",
            category="room_comfort",
            icon_key="tv",
            match_keywords=("tv", "tivi"),
        ),
    ]
    monkeypatch.setattr(amenity_catalog, "query_approved_amenities", lambda: entries)
    monkeypatch.setattr(
        amenity_catalog,
        "get_fast_llm",
        lambda **_: (_ for _ in ()).throw(AssertionError("LLM must not be called")),
    )

    assert amenity_catalog.bind_amenities(
        ["Hồ bơi ngoài trời", "swimming_pool", "Hồ bơi"], scope="hotel"
    ) == amenity_catalog.AmenityBindingResult(ids=("swimming_pool",), unresolved=(), created=0)
    assert amenity_catalog.bind_amenities(["Tivi"], scope="room").ids == ("tv",)


def test_resolve_hotel_amenity_ids_uses_only_approved_hotel_catalog_entries(monkeypatch):
    entries = [
        amenity_catalog.AmenityCatalogEntry(
            id="swimming_pool",
            label="Hồ bơi",
            label_en="Swimming pool",
            scope="hotel",
            category="wellness",
            icon_key="pool",
            match_keywords=("hồ bơi", "pool"),
        ),
        amenity_catalog.AmenityCatalogEntry(
            id="tv",
            label="TV",
            label_en="TV",
            scope="room",
            category="room_comfort",
            icon_key="tv",
            match_keywords=("tv", "tivi"),
        ),
    ]
    monkeypatch.setattr(amenity_catalog, "all_approved_amenities", lambda: tuple(entries))
    monkeypatch.setattr(
        amenity_catalog,
        "get_fast_llm",
        lambda **_: (_ for _ in ()).throw(AssertionError("LLM must not be called")),
    )

    result = amenity_catalog.resolve_hotel_amenity_ids(["pool", "tv", "unknown amenity"])

    assert result.ids == ("swimming_pool",)
    assert result.unresolved == ("tv", "unknown amenity")


def test_bind_amenities_reuses_a_hotel_catalog_item_for_a_room_value(monkeypatch):
    hair_dryer = amenity_catalog.AmenityCatalogEntry(
        id="hair_dryer",
        label="Máy sấy tóc",
        label_en="Hair Dryer",
        scope="hotel",
        category="room_comfort",
        icon_key="hair_dryer",
        match_keywords=("hair dryer", "máy sấy tóc"),
    )
    monkeypatch.setattr(amenity_catalog, "query_approved_amenities", lambda: [hair_dryer])

    result = amenity_catalog.bind_amenities(["Máy sấy tóc"], scope="room", persist=False)

    assert result.ids == ("hair_dryer",)
    assert result.unresolved == ()


def test_bind_amenities_matches_each_duplicate_raw_value_once_per_page(monkeypatch):
    tv = amenity_catalog.AmenityCatalogEntry(
        id="tv", label="TV", label_en="TV", scope="both", category="room_comfort",
        icon_key="tv", match_keywords=("tv", "tivi"),
    )
    calls = []
    original_match = amenity_catalog._match_catalog_entry
    monkeypatch.setattr(amenity_catalog, "query_approved_amenities", lambda: [tv])
    monkeypatch.setattr(
        amenity_catalog,
        "_match_catalog_entry",
        lambda raw, entries, scope, **kwargs: calls.append(raw) or original_match(raw, entries, scope, **kwargs),
    )

    result = amenity_catalog.bind_amenities(["Tivi", "Tivi", "Tivi"], scope="room", persist=False)

    assert result.ids == ("tv",)
    assert calls == ["Tivi"]


def test_bind_amenities_promotes_a_local_cross_scope_match_to_both(monkeypatch):
    persisted_rows = []

    class _Query:
        def upsert(self, rows, on_conflict):
            assert on_conflict == "id"
            persisted_rows.extend(rows)
            return self
        def execute(self): return SimpleNamespace(data=[])

    class _Client:
        def table(self, _name): return _Query()

    hair_dryer = amenity_catalog.AmenityCatalogEntry(
        id="hair_dryer",
        label="Máy sấy tóc",
        label_en="Hair Dryer",
        scope="hotel",
        category="room_comfort",
        icon_key="hair_dryer",
        match_keywords=("hair dryer", "máy sấy tóc"),
    )
    monkeypatch.setattr(amenity_catalog, "query_approved_amenities", lambda: [hair_dryer])
    monkeypatch.setattr(amenity_catalog, "get_supabase_client", lambda: _Client())

    result = amenity_catalog.bind_amenities(["Máy sấy tóc"], scope="room")

    assert result.ids == ("hair_dryer",)
    assert persisted_rows == [{
        "id": "hair_dryer", "label_vi": "Máy sấy tóc", "label_en": "Hair Dryer", "scope": "both",
        "category": "room_comfort", "icon_key": "hair_dryer",
        "match_keywords": ["hair dryer", "máy sấy tóc"], "is_approved": True,
    }]


def test_existing_model_selection_removes_the_alias_from_conflicting_catalog_rows(monkeypatch):
    persisted_rows = []

    class _Response:
        content = '''{"amenities":[{"id":"room_air_conditioning","existing_id":"air_conditioning","is_amenity":false}]}'''

    class _FastModel:
        def invoke(self, _messages): return _Response()

    class _Query:
        def upsert(self, rows, on_conflict):
            assert on_conflict == "id"
            persisted_rows.extend(rows)
            return self
        def execute(self): return SimpleNamespace(data=[])

    class _Client:
        def table(self, _name): return _Query()

    selected = amenity_catalog.AmenityCatalogEntry(
        id="air_conditioning", label="Air Conditioning", label_en="Air Conditioning", scope="both",
        category="room_comfort", match_keywords=("air conditioning",),
    )
    conflicting = amenity_catalog.AmenityCatalogEntry(
        id="air_conditioning_in_common_area", label="Common Area AC", label_en="Air Conditioning in Common Area",
        scope="hotel", category="facility", match_keywords=("air conditioning", "common area ac"),
    )
    monkeypatch.setattr(amenity_catalog, "get_fast_llm", lambda **_: _FastModel())
    monkeypatch.setattr(amenity_catalog, "get_supabase_client", lambda: _Client())

    amenity_catalog.discover_and_store_amenities(
        [{"id": "room_air_conditioning", "label": "Air conditioning"}],
        scope="room", existing_entries=[selected, conflicting],
    )

    rows_by_id = {row["id"]: row for row in persisted_rows}
    assert rows_by_id["air_conditioning_in_common_area"]["match_keywords"] == ["common area ac"]


def test_discovery_promotes_existing_hotel_item_when_classifying_room_alias(monkeypatch):
    class _Response:
        content = '''{"amenities":[{"id":"hair_dryer_in_room","existing_id":"hair_dryer","is_amenity":false}]}'''

    class _FastModel:
        def invoke(self, _messages): return _Response()

    hair_dryer = amenity_catalog.AmenityCatalogEntry(
        id="hair_dryer",
        label="Máy sấy tóc",
        label_en="Hair Dryer",
        scope="hotel",
        category="room_comfort",
        icon_key="hair_dryer",
        match_keywords=("hair dryer",),
    )
    monkeypatch.setattr(amenity_catalog, "get_fast_llm", lambda **_: _FastModel())

    entries = amenity_catalog.discover_and_store_amenities(
        [{"id": "hair_dryer_in_room", "label": "Hair dryer in room"}],
        scope="room",
        existing_entries=[hair_dryer],
        persist=False,
    )

    assert entries == [amenity_catalog.AmenityCatalogEntry(
        id="hair_dryer",
        label="Máy sấy tóc",
        label_en="Hair Dryer",
        scope="both",
        category="room_comfort",
        icon_key="hair_dryer",
        match_keywords=("hair dryer", "hair dryer in room"),
        source_id="hair_dryer_in_room",
    )]


def test_bind_amenities_batches_unique_unknown_values_and_creates_compatible_catalog_entries(monkeypatch):
    captured_candidates = []
    monkeypatch.setattr(amenity_catalog, "query_approved_amenities", lambda: [])

    def discover(candidates, *, scope, persist=True, existing_entries=()):
        captured_candidates.append((list(candidates), scope))
        return [
            amenity_catalog.AmenityCatalogEntry(
                id=candidate["id"],
                label=candidate["label"],
                label_en=candidate["label"],
                scope=scope,
                category="general",
                icon_key=None,
                match_keywords=(candidate["label"],),
            )
            for candidate in candidates
        ]

    monkeypatch.setattr(amenity_catalog, "discover_and_store_amenities", discover)
    values = [f"Unknown {index}" for index in range(9)] + ["Unknown 0"]

    result = amenity_catalog.bind_amenities(values, scope="room")

    assert [len(batch) for batch, _ in captured_candidates] == [8, 1]
    assert result.ids == tuple(f"unknown_{index}" for index in range(9))
    assert result.unresolved == ()
    assert result.created == 9
    assert [entry.id for entry in result.proposals] == [f"unknown_{index}" for index in range(9)]


def test_bind_amenities_keeps_unresolved_values_when_model_returns_incompatible_scope(monkeypatch):
    monkeypatch.setattr(amenity_catalog, "query_approved_amenities", lambda: [])
    monkeypatch.setattr(
        amenity_catalog,
        "discover_and_store_amenities",
        lambda candidates, *, scope, persist=True, existing_entries=(): [
            amenity_catalog.AmenityCatalogEntry(
                id="private_pool",
                label="Hồ bơi riêng",
                label_en="Private pool",
                scope="hotel",
                category="wellness",
                icon_key="pool",
                match_keywords=("hồ bơi riêng",),
            )
        ],
    )

    assert amenity_catalog.bind_amenities(["Hồ bơi riêng"], scope="room") == (
        amenity_catalog.AmenityBindingResult(ids=(), unresolved=("Hồ bơi riêng",), created=0)
    )


# ---------------------------------------------------------------------------
# Two-character token retention in `_match_terms`.
#
# Vietnamese labels are syllable-pairs, and stripping diacritics leaves many
# syllables exactly two letters ("lê" -> "le", "vị" -> "vi", "rẻ" -> "re").
# Dropping those collapsed a whole label to one token, and the "every phrase
# token is present" rule in `_phrase_match_score` then matched on that single
# token appearing anywhere in the request -- turning an unrelated phrase into
# a hard, wrong search filter (reported: "view đẹp" filtered on Dép lê).
# ---------------------------------------------------------------------------


def _entry(amenity_id: str, label: str, *keywords: str) -> amenity_catalog.AmenityCatalogEntry:
    return amenity_catalog.AmenityCatalogEntry(
        id=amenity_id, label=label, match_keywords=tuple(keywords), scope="hotel"
    )


_MATCH_CATALOG = (
    _entry("slippers", "Dép lê", "slippers", "dép lê"),
    _entry("essential_spices", "Gia vị thiết yếu", "gia vị", "essential spices"),
    _entry("swimming_pool", "Hồ bơi", "swimming pool", "hồ bơi"),
    _entry("sea_view", "Nhìn ra biển", "sea view", "nhìn ra biển", "view biển"),
)


def _resolve_one(monkeypatch, raw: str):
    monkeypatch.setattr(amenity_catalog, "all_approved_amenities", lambda: _MATCH_CATALOG)
    return amenity_catalog.resolve_hotel_amenity_ids([raw])


def test_two_letter_syllables_survive_tokenization():
    assert amenity_catalog._match_terms("dép lê") == {"dep", "le"}
    assert amenity_catalog._match_terms("gia vị") == {"gia", "vi"}
    # Single characters carry no meaning and stay dropped.
    assert amenity_catalog._match_terms("y tế a") == {"te"}


def test_unrelated_phrase_sharing_one_syllable_does_not_bind(monkeypatch):
    """"view đẹp" shares only "dep" with "Dép lê" -- it must not become a
    slippers filter, and an honest unresolved beats a confident wrong bind."""
    result = _resolve_one(monkeypatch, "view đẹp")
    assert result.ids == ()
    assert result.unresolved == ("view đẹp",)


def test_price_phrase_does_not_bind_to_a_spice_amenity(monkeypatch):
    """Same defect, second reported instance: "giá rẻ" vs "Gia vị"."""
    result = _resolve_one(monkeypatch, "giá rẻ")
    assert result.ids == ()
    assert result.unresolved == ("giá rẻ",)


def test_a_modified_amenity_phrase_still_binds_to_its_base(monkeypatch):
    """The rule this fix must NOT break: every token of "hồ bơi" is present
    in "hồ bơi ngoài trời", which is real evidence, not a coincidence."""
    assert _resolve_one(monkeypatch, "hồ bơi ngoài trời").ids == ("swimming_pool",)


def test_exact_label_still_binds(monkeypatch):
    assert _resolve_one(monkeypatch, "dép lê").ids == ("slippers",)


def test_colloquial_sea_view_spelling_binds_through_its_keyword(monkeypatch):
    """"view biển" is the phrasing users actually type; it resolves through
    the catalog keyword rather than lingering as an unsupported term."""
    assert _resolve_one(monkeypatch, "view biển").ids == ("sea_view",)
