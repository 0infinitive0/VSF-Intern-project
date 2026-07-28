from unittest.mock import MagicMock, patch

import pytest

from src.services.qdrant_schema import point_id
from src.services.qdrant_writer import (
    UpsertStats,
    _build_payload,
    _strip_control_chars,
    _swap_alias,
    upsert_hotels,
)


def _fake_hotel(source_platform="agoda", source_hotel_id=1, canonical_hotel_key=None):
    return {
        "source_platform": source_platform,
        "source_hotel_id": source_hotel_id,
        "retrieval": {
            "embedding_text": f"Hotel: Test {source_hotel_id}",
            "payload": {
                "source_platform": source_platform,
                "source_hotel_id": source_hotel_id,
                "name": f"Test Hotel {source_hotel_id}",
                "star_rating": 4.0,
            },
            "grounding_facts": {"name": f"Test Hotel {source_hotel_id}", "source_url": "https://x"},
        },
        "canonical": {
            "canonical_hotel_key": canonical_hotel_key,
            "group_review_status": "auto_approved" if canonical_hotel_key else "ungrouped",
        },
    }


def _client_stub():
    client = MagicMock()
    client.collection_exists.return_value = False
    client.get_collection.return_value = MagicMock(payload_schema={})
    client.get_collections.return_value = MagicMock(collections=[])
    client.get_aliases.return_value = MagicMock(aliases=[])
    return client


# --- _strip_control_chars ---

def test_strip_control_chars_from_string():
    assert _strip_control_chars("a\x00b\x1fc") == "abc"


def test_strip_control_chars_recurses_into_list_and_dict():
    value = {"a": ["x\x00y"], "b": "z\x0c"}
    assert _strip_control_chars(value) == {"a": ["xy"], "b": "z"}


def test_strip_control_chars_passes_through_non_string_scalars():
    assert _strip_control_chars(42) == 42
    assert _strip_control_chars(None) is None


# --- _build_payload ---

def test_build_payload_merges_identity_map_fields():
    hotel = _fake_hotel(canonical_hotel_key="grp-1")
    identity = {"destination_id": "dest-1", "supabase_hotel_id": "sb-1"}

    payload = _build_payload(hotel, identity)

    assert payload["destination_id"] == "dest-1"
    assert payload["supabase_hotel_id"] == "sb-1"
    assert payload["canonical_hotel_key"] == "grp-1"
    assert payload["group_review_status"] == "auto_approved"
    assert payload["name"] == "Test Hotel 1"


def test_build_payload_missing_identity_yields_none_not_error():
    hotel = _fake_hotel()
    payload = _build_payload(hotel, {})
    assert payload["destination_id"] is None
    assert payload["supabase_hotel_id"] is None


def test_build_payload_strips_control_chars_in_grounding_facts():
    hotel = _fake_hotel()
    hotel["retrieval"]["grounding_facts"]["name"] = "Bad\x00Name"
    payload = _build_payload(hotel, {})
    assert payload["grounding_facts"]["name"] == "BadName"


# --- _swap_alias ---

def test_swap_alias_deletes_literal_collection_sharing_the_alias_name():
    client = MagicMock()
    collection_stub = MagicMock()
    collection_stub.name = "hotels_vector"
    client.get_collections.return_value = MagicMock(collections=[collection_stub])
    client.get_aliases.return_value = MagicMock(aliases=[])

    _swap_alias(client, "hotels_vector", "hotels_vector_abc123")

    client.delete_collection.assert_called_once_with("hotels_vector")
    client.update_collection_aliases.assert_called_once()


def test_swap_alias_replaces_existing_alias():
    client = MagicMock()
    client.get_collections.return_value = MagicMock(collections=[])
    existing_alias = MagicMock()
    existing_alias.alias_name = "hotels_vector"
    client.get_aliases.return_value = MagicMock(aliases=[existing_alias])

    _swap_alias(client, "hotels_vector", "hotels_vector_new")

    client.delete_collection.assert_not_called()
    operations = client.update_collection_aliases.call_args.kwargs["change_aliases_operations"]
    assert len(operations) == 2  # delete old alias + create new one


def test_swap_alias_first_run_no_prior_collection_or_alias():
    client = MagicMock()
    client.get_collections.return_value = MagicMock(collections=[])
    client.get_aliases.return_value = MagicMock(aliases=[])

    _swap_alias(client, "hotels_vector", "hotels_vector_first")

    client.delete_collection.assert_not_called()
    operations = client.update_collection_aliases.call_args.kwargs["change_aliases_operations"]
    assert len(operations) == 1  # just the create


# --- upsert_hotels ---

@patch("src.services.qdrant_writer.get_embeddings")
def test_upsert_hotels_embeds_and_upserts_all_hotels(mock_get_embeddings):
    mock_embeddings = MagicMock()
    mock_embeddings.embed_documents.return_value = [[0.1, 0.2], [0.3, 0.4]]
    mock_get_embeddings.return_value = mock_embeddings

    client = _client_stub()
    hotels = [_fake_hotel(source_hotel_id=1), _fake_hotel(source_hotel_id=2)]

    stats = upsert_hotels(client, hotels, identity_map={}, batch_size=100)

    assert isinstance(stats, UpsertStats)
    assert stats.hotels_embedded == 2
    assert stats.hotels_upserted == 2
    assert stats.identity_resolved == 0
    client.upsert.assert_called_once()
    client.update_collection_aliases.assert_called_once()


@patch("src.services.qdrant_writer.get_embeddings")
def test_upsert_hotels_point_ids_are_deterministic(mock_get_embeddings):
    mock_embeddings = MagicMock()
    mock_embeddings.embed_documents.return_value = [[0.1, 0.2]]
    mock_get_embeddings.return_value = mock_embeddings

    client = _client_stub()
    hotels = [_fake_hotel(source_platform="agoda", source_hotel_id=42)]

    upsert_hotels(client, hotels, identity_map={}, batch_size=100)

    points = client.upsert.call_args.kwargs["points"]
    assert points[0].id == point_id("hotel", "agoda", 42)


@patch("src.services.qdrant_writer.get_embeddings")
def test_upsert_hotels_identity_map_resolved_count(mock_get_embeddings):
    mock_embeddings = MagicMock()
    mock_embeddings.embed_documents.return_value = [[0.1, 0.2], [0.3, 0.4]]
    mock_get_embeddings.return_value = mock_embeddings

    client = _client_stub()
    hotels = [_fake_hotel(source_hotel_id=1), _fake_hotel(source_hotel_id=2)]
    identity_map = {"agoda:1": {"destination_id": "d1", "supabase_hotel_id": "s1"}}

    stats = upsert_hotels(client, hotels, identity_map=identity_map, batch_size=100)

    assert stats.identity_resolved == 1
    points = client.upsert.call_args.kwargs["points"]
    payload_by_id = {p.id: p.payload for p in points}
    resolved_point = payload_by_id[point_id("hotel", "agoda", 1)]
    assert resolved_point["destination_id"] == "d1"
    unresolved_point = payload_by_id[point_id("hotel", "agoda", 2)]
    assert unresolved_point["destination_id"] is None


@patch("src.services.qdrant_writer.get_embeddings")
def test_upsert_hotels_failure_before_swap_drops_staging_collection_and_reraises(mock_get_embeddings):
    mock_embeddings = MagicMock()
    mock_embeddings.embed_documents.return_value = [[0.1, 0.2]]
    mock_get_embeddings.return_value = mock_embeddings

    client = _client_stub()
    client.upsert.side_effect = RuntimeError("boom")
    hotels = [_fake_hotel(source_hotel_id=1)]

    with pytest.raises(RuntimeError, match="boom"):
        upsert_hotels(client, hotels, identity_map={}, batch_size=100)

    client.delete_collection.assert_called_once()
    client.update_collection_aliases.assert_not_called()


@patch("src.services.qdrant_writer.get_embeddings")
def test_upsert_hotels_failure_during_swap_preserves_staging_collection(mock_get_embeddings):
    """The incident this guards against: if the alias swap itself fails
    (e.g. after the pre-existing literal collection was already deleted),
    the staging collection — the only surviving copy of the corpus — must
    NOT also be deleted."""
    mock_embeddings = MagicMock()
    mock_embeddings.embed_documents.return_value = [[0.1, 0.2]]
    mock_get_embeddings.return_value = mock_embeddings

    client = _client_stub()
    client.update_collection_aliases.side_effect = RuntimeError("alias swap boom")
    hotels = [_fake_hotel(source_hotel_id=1)]

    with pytest.raises(RuntimeError, match="alias swap boom"):
        upsert_hotels(client, hotels, identity_map={}, batch_size=100)

    client.delete_collection.assert_not_called()


@patch("src.services.qdrant_writer.get_embeddings")
def test_upsert_hotels_sweep_failure_after_successful_swap_does_not_raise(mock_get_embeddings):
    mock_embeddings = MagicMock()
    mock_embeddings.embed_documents.return_value = [[0.1, 0.2]]
    mock_get_embeddings.return_value = mock_embeddings

    client = _client_stub()
    # First get_collections() call is the swap's literal-collection check;
    # make the second (the sweep) raise instead, to isolate the sweep failure.
    client.get_collections.side_effect = [
        MagicMock(collections=[]),
        RuntimeError("sweep boom"),
    ]
    hotels = [_fake_hotel(source_hotel_id=1)]

    stats = upsert_hotels(client, hotels, identity_map={}, batch_size=100)

    assert stats.hotels_upserted == 1
    client.update_collection_aliases.assert_called_once()
    client.delete_collection.assert_not_called()


@patch("src.services.qdrant_writer.get_embeddings")
def test_upsert_hotels_oversized_payload_raises_before_upsert(mock_get_embeddings):
    mock_embeddings = MagicMock()
    mock_embeddings.embed_documents.return_value = [[0.1, 0.2]]
    mock_get_embeddings.return_value = mock_embeddings

    client = _client_stub()
    hotel = _fake_hotel(source_hotel_id=1)
    # Oversized grounding_facts field the DAG-side gate (which only measures
    # retrieval["payload"]) would never see.
    hotel["retrieval"]["grounding_facts"]["warnings"] = ["x" * 100_000]

    with pytest.raises(ValueError, match="exceeding"):
        upsert_hotels(client, [hotel], identity_map={}, batch_size=100)

    client.upsert.assert_not_called()
    client.delete_collection.assert_called_once()
    client.update_collection_aliases.assert_not_called()


def test_upsert_hotels_empty_list_raises_without_touching_client():
    client = _client_stub()

    with pytest.raises(ValueError, match="empty"):
        upsert_hotels(client, [], identity_map={}, batch_size=100)

    client.upsert.assert_not_called()
    client.update_collection_aliases.assert_not_called()


@patch("src.services.qdrant_writer.get_embeddings")
@patch("src.services.qdrant_writer.time.sleep", return_value=None)
def test_upsert_hotels_embed_retries_then_succeeds(_mock_sleep, mock_get_embeddings):
    mock_embeddings = MagicMock()
    mock_embeddings.embed_documents.side_effect = [
        ConnectionError("timeout"),
        [[0.1, 0.2]],
    ]
    mock_get_embeddings.return_value = mock_embeddings

    client = _client_stub()
    hotels = [_fake_hotel(source_hotel_id=1)]

    stats = upsert_hotels(client, hotels, identity_map={}, batch_size=100)

    assert stats.hotels_upserted == 1
    assert mock_embeddings.embed_documents.call_count == 2
