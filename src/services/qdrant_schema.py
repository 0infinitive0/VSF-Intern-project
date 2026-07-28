"""Qdrant collection schema: deterministic point IDs, collection specs, and
idempotent collection/index creation. Single source of truth so every sync
script declares fields in one place instead of copy-pasting."""

import uuid
from dataclasses import dataclass, field

from qdrant_client import QdrantClient
from qdrant_client.http.models import Distance

# Frozen namespace. Regenerating this orphans every existing point and
# silently re-duplicates the corpus — never change it.
_NAMESPACE = uuid.UUID("6f1c9e4a-2d1b-4f8e-9a3c-0b5d7e8f1a20")


def point_id(kind: str, *parts: str) -> str:
    """Deterministic UUID5 for a natural key. Same input -> same output,
    across processes and runs (unlike `hash()`, which is salted per-process)."""
    key = ":".join([kind, *(str(p) for p in parts)])
    return str(uuid.uuid5(_NAMESPACE, key))


VECTOR_SIZE = 1024  # bge-m3 dense
DISTANCE = Distance.COSINE


@dataclass(frozen=True)
class CollectionSpec:
    name: str
    payload_indexes: dict[str, str] = field(default_factory=dict)
    vector_size: int = VECTOR_SIZE
    distance: Distance = DISTANCE


# get_vector_store() (src/services/vector_store.py) builds a LangChain
# QdrantVectorStore with its default metadata_payload_key="metadata" — every
# Document.metadata field lands nested at payload["metadata"][field], not at
# the top level. Index keys must use this dot-path prefix to match what's
# actually stored, or the index silently matches nothing. Existing filter
# code (poc_trip_planner.py, routes.py) still queries flat keys and is
# unchanged by this phase — see the Phase 2 report for that gap.
_METADATA_PREFIX = "metadata."


def _metadata_indexes(fields: dict[str, str]) -> dict[str, str]:
    return {f"{_METADATA_PREFIX}{name}": schema for name, schema in fields.items()}


ATTRACTIONS_VECTOR = CollectionSpec(
    name="attractions_vector",
    payload_indexes=_metadata_indexes({
        "destination_id": "keyword",
        "category": "keyword",
        "is_tour": "bool",
    }),
)

HOTELS_VECTOR = CollectionSpec(
    name="hotels_vector",
    payload_indexes=_metadata_indexes({
        "destination_name": "keyword",
        "source_platform": "keyword",
        "price_tier": "keyword",
        "amenity_keys": "keyword",
        "star_rating": "float",
        # Not yet produced by build_hotel_payload() — indexing an absent
        # field is harmless (matches nothing, costs nothing). Phase 4 wires
        # these up; do not add filter code against them before then.
        "destination_id": "keyword",
        "canonical_hotel_key": "keyword",
    }),
)

ROOMS_VECTOR = CollectionSpec(
    name="rooms_vector",
    payload_indexes=_metadata_indexes({
        "source_platform": "keyword",
        "source_hotel_id": "keyword",
        "max_guests": "integer",
    }),
)


def ensure_collection(client: QdrantClient, spec: CollectionSpec) -> None:
    """Idempotent: creates the collection if absent, and creates only the
    payload indexes missing from an existing collection."""
    from qdrant_client.http.models import VectorParams

    if not client.collection_exists(spec.name):
        client.create_collection(
            collection_name=spec.name,
            vectors_config=VectorParams(size=spec.vector_size, distance=spec.distance),
        )

    existing = client.get_collection(spec.name).payload_schema
    for field_name, schema_type in spec.payload_indexes.items():
        if field_name not in existing:
            client.create_payload_index(spec.name, field_name, field_schema=schema_type)
