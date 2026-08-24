from types import SimpleNamespace

import src.services.trip_planner as trip_planner


class _DestinationQuery:
    def select(self, *_args):
        return self

    def ilike(self, *_args):
        return self

    def limit(self, *_args):
        return self

    def execute(self):
        return SimpleNamespace(data=[{"id": "dest-da-nang"}])


def test_destination_lookup_reuses_normalized_name_within_ttl(monkeypatch):
    calls = 0

    class _Client:
        def table(self, name):
            nonlocal calls
            assert name == "destinations"
            calls += 1
            return _DestinationQuery()

    trip_planner.clear_destination_id_cache()
    monkeypatch.setattr(trip_planner, "get_supabase_client", lambda: _Client())

    assert trip_planner._get_destination_id("Đà Nẵng") == "dest-da-nang"
    assert trip_planner._get_destination_id("du lịch Đà Nẵng") == "dest-da-nang"
    assert calls == 1
