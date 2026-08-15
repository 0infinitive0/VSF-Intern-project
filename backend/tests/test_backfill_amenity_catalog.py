from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

from scripts import backfill_amenity_catalog as backfill
from src.services.amenity_catalog import AmenityBindingResult, AmenityCatalogEntry


def _args(path: Path, **overrides):
    values = {
        "table": "hotels",
        "page_size": 2,
        "max_rows": None,
        "only_id": None,
        "checkpoint": str(path),
        "resume": False,
        "dry_run": True,
        "catalog_only": False,
        "reset_checkpoint": False,
    }
    values.update(overrides)
    return Namespace(**values)


def test_checkpoint_resume_validates_command_options(tmp_path):
    path = tmp_path / "checkpoint.json"
    checkpoint = backfill._new_checkpoint(_args(path))
    backfill._write_checkpoint(path, checkpoint)

    assert backfill._load_checkpoint(path, _args(path))["page_size"] == 2

    try:
        backfill._load_checkpoint(path, _args(path, page_size=3))
    except ValueError as exc:
        assert "do not match" in str(exc)
    else:
        raise AssertionError("mismatched checkpoint options must fail")


def test_dry_run_writes_checkpoint_without_updating_rows(tmp_path, monkeypatch):
    checkpoint = tmp_path / "checkpoint.json"
    rows = [
        {"id": "1", "amenities": ["Wi-Fi"]},
        {"id": "2", "amenities": ["Hồ bơi"]},
    ]
    updates = []

    class Query:
        def __init__(self, table):
            self.table_name = table
            self.after_id = None

        def select(self, _fields): return self
        def order(self, _field): return self
        def limit(self, _value): return self
        def gt(self, _field, value):
            self.after_id = value
            return self
        def update(self, value):
            updates.append((self.table_name, value))
            return self
        def eq(self, _field, _value): return self
        def execute(self):
            page = [row for row in rows if self.after_id is None or row["id"] > self.after_id]
            return SimpleNamespace(data=page if self.table_name == "hotels" else [])

    class Client:
        def table(self, name): return Query(name)

    monkeypatch.setattr(backfill, "get_supabase_client", lambda: Client())
    monkeypatch.setattr(
        backfill,
        "bind_amenity_rows",
        lambda values_by_row, *, scope, persist=True: [
            AmenityBindingResult(("wifi",) if values[0] == "Wi-Fi" else ("swimming_pool",), (), 0)
            for values in values_by_row
        ],
    )

    assert backfill.run(_args(checkpoint)) == 0
    assert updates == []
    saved = backfill.json.loads(checkpoint.read_text(encoding="utf-8"))
    assert saved["completed"] is True
    assert saved["counts"]["updated"] == 2
    assert saved["proposals"] == []


def test_dry_run_records_sanitized_proposed_catalog_rows(tmp_path, monkeypatch):
    checkpoint = tmp_path / "checkpoint.json"
    rows = [{"id": "1", "amenities": ["Sân thượng"]}]

    class Query:
        def __init__(self, table):
            self.table_name = table
            self.after_id = None

        def select(self, _fields): return self
        def order(self, _field): return self
        def limit(self, _value): return self
        def gt(self, _field, value):
            self.after_id = value
            return self
        def eq(self, _field, _value): return self
        def execute(self):
            page = [row for row in rows if self.after_id is None or row["id"] > self.after_id]
            return SimpleNamespace(data=page if self.table_name == "hotels" else [])

    class Client:
        def table(self, name): return Query(name)

    proposal = AmenityCatalogEntry(
        id="rooftop_terrace", label="Sân thượng", label_en="Rooftop terrace", scope="hotel",
        category="outdoor", icon_key="roofing", match_keywords=("sân thượng", "rooftop terrace"),
    )
    monkeypatch.setattr(backfill, "get_supabase_client", lambda: Client())
    monkeypatch.setattr(
        backfill, "bind_amenity_rows",
        lambda values_by_row, *, scope, persist=True: [
            AmenityBindingResult(("rooftop_terrace",), (), 1, (proposal,)) for _ in values_by_row
        ],
    )

    assert backfill.run(_args(checkpoint)) == 0
    saved = backfill.json.loads(checkpoint.read_text(encoding="utf-8"))
    assert saved["proposals"] == [{
        "table": "hotels", "id": "1", "source_values": ["Sân thượng"], "catalog_rows": [{
            "id": "rooftop_terrace", "label_vi": "Sân thượng", "label_en": "Rooftop terrace", "scope": "hotel",
            "category": "outdoor", "icon_key": "roofing", "match_keywords": ["sân thượng", "rooftop terrace"],
        }],
    }]


def test_terminal_json_escapes_unicode_for_legacy_windows_console():
    assert "\\u00e2" in backfill._terminal_json({"label_vi": "Sân thượng"}, encoding="cp1252")
    assert "Sân thượng" in backfill._terminal_json({"label_vi": "Sân thượng"}, encoding="utf-8")


def test_backfill_counts_each_created_catalog_id_once_per_page(tmp_path, monkeypatch):
    checkpoint = tmp_path / "checkpoint.json"
    rows = [{"id": "1", "amenities": ["A"]}, {"id": "2", "amenities": ["A"]}]

    class Query:
        def __init__(self, table):
            self.table_name = table
            self.after_id = None

        def select(self, _fields): return self
        def order(self, _field): return self
        def limit(self, _value): return self
        def gt(self, _field, value):
            self.after_id = value
            return self
        def eq(self, _field, _value): return self
        def execute(self):
            page = [row for row in rows if self.after_id is None or row["id"] > self.after_id]
            return SimpleNamespace(data=page if self.table_name == "hotels" else [])

    class Client:
        def table(self, name): return Query(name)

    proposal = AmenityCatalogEntry("a", "A", ("a",), label_en="A", category="facility")
    monkeypatch.setattr(backfill, "get_supabase_client", lambda: Client())
    monkeypatch.setattr(
        backfill, "bind_amenity_rows",
        lambda values_by_row, *, scope, persist=True: [
            AmenityBindingResult(("a",), (), 1, (proposal,)) for _ in values_by_row
        ],
    )

    assert backfill.run(_args(checkpoint)) == 0
    saved = backfill.json.loads(checkpoint.read_text(encoding="utf-8"))
    assert saved["counts"]["catalog_added"] == 1


def test_catalog_only_builds_bindings_without_rewriting_source_rows(tmp_path, monkeypatch):
    checkpoint = tmp_path / "checkpoint.json"
    rows = [{"id": "1", "room_facilities": ["Hair dryer"]}]
    updates = []

    class Query:
        def __init__(self, table):
            self.table_name = table
            self.after_id = None

        def select(self, _fields): return self
        def order(self, _field): return self
        def limit(self, _value): return self
        def gt(self, _field, value):
            self.after_id = value
            return self
        def update(self, value):
            updates.append((self.table_name, value))
            return self
        def eq(self, _field, _value): return self
        def execute(self):
            page = [row for row in rows if self.after_id is None or row["id"] > self.after_id]
            return SimpleNamespace(data=page if self.table_name == "rooms" else [])

    class Client:
        def table(self, name): return Query(name)

    monkeypatch.setattr(backfill, "get_supabase_client", lambda: Client())
    monkeypatch.setattr(
        backfill,
        "bind_amenity_rows",
        lambda values_by_row, *, scope, persist=True: [
            AmenityBindingResult(("hair_dryer",), (), 0) for _ in values_by_row
        ],
    )

    assert backfill.run(_args(checkpoint, table="rooms", dry_run=False, catalog_only=True)) == 0
    assert updates == []
    saved = backfill.json.loads(checkpoint.read_text(encoding="utf-8"))
    assert saved["counts"] == {"processed": 1, "updated": 0, "unchanged": 1, "failed": 0, "catalog_added": 0}


def test_catalog_only_resolves_each_distinct_source_value_once(tmp_path, monkeypatch):
    checkpoint = tmp_path / "checkpoint.json"
    rows = [
        {"id": "1", "room_facilities": ["Hair dryer", "Wi-Fi"]},
        {"id": "2", "room_facilities": ["Hair dryer"]},
    ]
    captured_values = []

    class Query:
        def __init__(self, table):
            self.table_name = table
            self.after_id = None

        def select(self, _fields): return self
        def order(self, _field): return self
        def limit(self, _value): return self
        def gt(self, _field, value):
            self.after_id = value
            return self
        def eq(self, _field, value):
            self.after_id = value
            return self
        def execute(self):
            page = [row for row in rows if self.after_id is None or row["id"] > self.after_id]
            return SimpleNamespace(data=page if self.table_name == "rooms" else [])

    class Client:
        def table(self, name): return Query(name)

    monkeypatch.setattr(backfill, "get_supabase_client", lambda: Client())
    monkeypatch.setattr(
        backfill,
        "bind_amenity_rows",
        lambda values_by_row, *, scope, persist=True: (
            captured_values.append(list(values_by_row[0]))
            or [AmenityBindingResult(tuple(values_by_row[0]), (), 0)]
        ),
    )

    assert backfill.run(_args(checkpoint, table="rooms", dry_run=False, catalog_only=True)) == 0
    assert captured_values == [["Hair dryer", "Wi-Fi"]]
    saved = backfill.json.loads(checkpoint.read_text(encoding="utf-8"))
    assert saved["counts"]["processed"] == 2
    assert saved["counts"]["updated"] == 0
