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
        assert name == "hotel_amenity_catalog"
        self.query = _Query(self.rows)
        return self.query


def test_query_approved_amenities_filters_by_sanitized_ids(monkeypatch):
    client = _Client(
        [
            {"id": "parking", "label": "Bãi đỗ xe", "match_keywords": ["parking", "bãi đỗ xe"]},
            {"id": "wifi", "label": "Wi-Fi", "match_keywords": ["wifi"]},
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


def test_discover_and_store_amenities_inserts_only_fast_model_approved_candidates(monkeypatch):
    inserted_rows = []
    captured_messages = []

    class _Response:
        content = '''{
          "amenities": [
            {"id": "spa", "is_amenity": true, "match_keywords": ["wellness", "phòng spa"]},
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

        def execute(self):
            return SimpleNamespace(data=inserted_rows)

    class _InsertClient:
        def table(self, name):
            assert name == "hotel_amenity_catalog"
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
            "label": "phòng spa",
            "match_keywords": ["spa", "wellness", "phòng spa"],
            "source": "fast_model",
            "is_approved": True,
        }
    ]
    assert "Vietnamese" in captured_messages[0].content
