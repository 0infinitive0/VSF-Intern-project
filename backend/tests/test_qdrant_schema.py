import uuid
from unittest.mock import MagicMock

from src.services.qdrant_schema import (
    ATTRACTIONS_VECTOR,
    CollectionSpec,
    ensure_collection,
    point_id,
)


def test_point_id_same_input_same_output():
    assert point_id("attraction", "abc-123") == point_id("attraction", "abc-123")


def test_point_id_different_kind_different_output():
    assert point_id("attraction", "1") != point_id("room", "1")


def test_point_id_is_valid_uuid():
    uuid.UUID(point_id("attraction", "abc-123"))


def test_point_id_pinned_literal():
    # Pins the frozen namespace. If this fails, the namespace changed and
    # every existing Qdrant point would be orphaned/re-duplicated.
    assert point_id("attraction", "abc-123") == "9bc3c755-3cfd-5254-86d1-69d3a45663a7"


def test_ensure_collection_creates_when_absent():
    client = MagicMock()
    client.collection_exists.return_value = False
    client.get_collection.return_value = MagicMock(payload_schema={})

    spec = CollectionSpec(name="test_vector", payload_indexes={"foo": "keyword"})
    ensure_collection(client, spec)

    client.create_collection.assert_called_once()
    client.create_payload_index.assert_called_once_with("test_vector", "foo", field_schema="keyword")


def test_ensure_collection_noop_when_indexes_present():
    client = MagicMock()
    client.collection_exists.return_value = True
    client.get_collection.return_value = MagicMock(payload_schema={"foo": object()})

    spec = CollectionSpec(name="test_vector", payload_indexes={"foo": "keyword"})
    ensure_collection(client, spec)

    client.create_collection.assert_not_called()
    client.create_payload_index.assert_not_called()


def test_ensure_collection_creates_only_missing_indexes():
    client = MagicMock()
    client.collection_exists.return_value = True
    client.get_collection.return_value = MagicMock(payload_schema={"foo": object()})

    spec = CollectionSpec(name="test_vector", payload_indexes={"foo": "keyword", "bar": "integer"})
    ensure_collection(client, spec)

    client.create_payload_index.assert_called_once_with("test_vector", "bar", field_schema="integer")


def test_attractions_vector_spec_matches_existing_sync_fields():
    # QdrantVectorStore's default metadata_payload_key="metadata" nests every
    # Document.metadata field under payload["metadata"][field] — index keys
    # must use that dot-path prefix to match what's actually stored.
    assert set(ATTRACTIONS_VECTOR.payload_indexes) == {
        "metadata.destination_id",
        "metadata.category",
        "metadata.is_tour",
    }
