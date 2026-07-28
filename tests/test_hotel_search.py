from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from src.services.hotel_search import _hydrate, _parse_scraped_at, search_hotels
from src.services.qdrant_writer import PAYLOAD_VERSION


def _payload(
    source_platform="agoda",
    source_hotel_id=1,
    canonical_hotel_key=None,
    group_review_status="ungrouped",
    scraped_at=None,
    name="Test Hotel",
    supabase_hotel_id=None,
    payload_version=PAYLOAD_VERSION,
    star_rating=None,
):
    return {
        "source_platform": source_platform,
        "source_hotel_id": source_hotel_id,
        "supabase_hotel_id": supabase_hotel_id,
        "name": name,
        "canonical_hotel_key": canonical_hotel_key,
        "group_review_status": group_review_status,
        "payload_version": payload_version,
        "star_rating": star_rating,
        "grounding_facts": {
            "source_platform": source_platform,
            "source_hotel_id": source_hotel_id,
            "name": name,
            "source_url": "https://example.com/x",
            "lowest_price": 500000,
            "currency": "VND",
            "review_count": 10,
            "scraped_at": scraped_at,
        },
    }


def _point(payload, score=0.9):
    point = MagicMock()
    point.payload = payload
    point.score = score
    return point


def _patch_no_llm_filter():
    """Most tests exercise the Qdrant-query path, not the LLM query-cleaning
    step — patch it to a no-op so tests don't need a live Ollama."""
    return patch(
        "src.services.hotel_search.extract_search_filters",
        return_value={},
    )


# --- _parse_scraped_at ---

def test_parse_scraped_at_none_stays_none():
    assert _parse_scraped_at(None) is None


def test_parse_scraped_at_parses_iso_string():
    parsed = _parse_scraped_at("2026-07-22T10:00:00+00:00")
    assert parsed == datetime(2026, 7, 22, 10, 0, tzinfo=timezone.utc)


def test_parse_scraped_at_passes_through_datetime():
    dt = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert _parse_scraped_at(dt) is dt


def test_parse_scraped_at_unparseable_returns_none_not_raise():
    assert _parse_scraped_at("not-a-date") is None


# --- _hydrate ---

def test_hydrate_flattens_grounding_facts_onto_root():
    payload = _payload(scraped_at="2026-07-22T10:00:00+00:00")
    hotel = _hydrate(payload)

    assert hotel["source_platform"] == "agoda"
    assert hotel["source_hotel_id"] == 1
    assert hotel["name"] == "Test Hotel"
    assert hotel["lowest_price"] == 500000
    assert hotel["currency"] == "VND"
    assert hotel["source_url"] == "https://example.com/x"
    assert hotel["scraped_at"] == datetime(2026, 7, 22, 10, 0, tzinfo=timezone.utc)
    assert hotel["retrieval"]["grounding_facts"] == payload["grounding_facts"]


def test_hydrate_missing_scraped_at_does_not_raise():
    payload = _payload(scraped_at=None)
    hotel = _hydrate(payload)
    assert hotel["scraped_at"] is None


def test_hydrate_carries_canonical_fields():
    payload = _payload(canonical_hotel_key="grp-1", group_review_status="auto_approved")
    hotel = _hydrate(payload)
    assert hotel["canonical"]["canonical_hotel_key"] == "grp-1"
    assert hotel["canonical"]["group_review_status"] == "auto_approved"


def test_hydrate_carries_supabase_hotel_id():
    payload = _payload(supabase_hotel_id="sb-1")
    hotel = _hydrate(payload)
    assert hotel["supabase_hotel_id"] == "sb-1"


# --- search_hotels ---

@patch("src.services.hotel_search.get_qdrant_client")
@patch("src.services.hotel_search.get_embeddings")
def test_search_hotels_returns_ungrouped_singles(mock_get_embeddings, mock_get_client):
    mock_get_embeddings.return_value.embed_query.return_value = [0.1, 0.2]
    client = MagicMock()
    client.query_points.return_value = MagicMock(
        points=[_point(_payload(source_hotel_id=1)), _point(_payload(source_hotel_id=2))]
    )
    mock_get_client.return_value = client

    with _patch_no_llm_filter():
        results = search_hotels("hotel in Da Nang", k=5, use_llm_filter=False)

    assert len(results) == 2
    client.scroll.assert_not_called()  # no auto_approved groups to complete


@patch("src.services.hotel_search.get_qdrant_client")
@patch("src.services.hotel_search.get_embeddings")
def test_search_hotels_completes_group_beyond_top_k_window(mock_get_embeddings, mock_get_client):
    """The correctness property phase-05 calls out: an Agoda+Booking pair
    returns one result with two offers even when one member ranks outside
    the top-k vector-query window — because completion comes from a second,
    filtered lookup on canonical_hotel_key, not from the fetch window."""
    mock_get_embeddings.return_value.embed_query.return_value = [0.1, 0.2]
    client = MagicMock()
    # Only the Agoda listing ranks in the top-k vector query...
    top_k_hit = _payload(
        source_platform="agoda", source_hotel_id=1,
        canonical_hotel_key="grp-1", group_review_status="auto_approved",
    )
    client.query_points.return_value = MagicMock(points=[_point(top_k_hit)])
    # ...but the group-completion scroll finds both members.
    booking_twin = _payload(
        source_platform="booking", source_hotel_id=2,
        canonical_hotel_key="grp-1", group_review_status="auto_approved",
    )
    client.scroll.return_value = ([MagicMock(payload=top_k_hit), MagicMock(payload=booking_twin)], None)
    mock_get_client.return_value = client

    results = search_hotels("hotel in Da Nang", k=5, use_llm_filter=False)

    assert len(results) == 1
    assert len(results[0]["offers"]) == 2
    client.scroll.assert_called_once()
    scroll_kwargs = client.scroll.call_args.kwargs
    match_any = scroll_kwargs["scroll_filter"].must[0].match
    assert match_any.any == ["grp-1"]  # single call, not one per group


@patch("src.services.hotel_search.get_qdrant_client")
@patch("src.services.hotel_search.get_embeddings")
def test_search_hotels_pending_review_group_stays_separate(mock_get_embeddings, mock_get_client):
    mock_get_embeddings.return_value.embed_query.return_value = [0.1, 0.2]
    client = MagicMock()
    client.query_points.return_value = MagicMock(
        points=[
            _point(_payload(source_hotel_id=1, canonical_hotel_key="grp-2", group_review_status="pending_review")),
            _point(_payload(source_hotel_id=2, canonical_hotel_key="grp-2", group_review_status="pending_review")),
        ]
    )
    mock_get_client.return_value = client

    results = search_hotels("hotel in Da Nang", k=5, use_llm_filter=False)

    assert len(results) == 2  # not collapsed — pending_review never merges
    client.scroll.assert_not_called()  # only auto_approved groups get completed


@patch("src.services.hotel_search.get_qdrant_client")
@patch("src.services.hotel_search.get_embeddings")
def test_search_hotels_member_missing_scraped_at_does_not_raise(mock_get_embeddings, mock_get_client):
    mock_get_embeddings.return_value.embed_query.return_value = [0.1, 0.2]
    client = MagicMock()
    client.query_points.return_value = MagicMock(
        points=[
            _point(_payload(source_hotel_id=1, scraped_at="2026-07-22T10:00:00+00:00")),
            _point(_payload(source_hotel_id=2, scraped_at=None)),
        ]
    )
    mock_get_client.return_value = client

    results = search_hotels("hotel in Da Nang", k=5, use_llm_filter=False)  # must not raise TypeError

    assert len(results) == 2


@patch("src.services.hotel_search.get_qdrant_client")
@patch("src.services.hotel_search.get_embeddings")
def test_search_hotels_destination_filter_applied(mock_get_embeddings, mock_get_client):
    mock_get_embeddings.return_value.embed_query.return_value = [0.1, 0.2]
    client = MagicMock()
    client.query_points.return_value = MagicMock(points=[])
    mock_get_client.return_value = client

    search_hotels("hotel", destination_id="dest-1", k=5, use_llm_filter=False)

    _, kwargs = client.query_points.call_args
    query_filter = kwargs["query_filter"]
    assert query_filter is not None
    # Flat key, not "metadata.destination_id" — the exact bug class this
    # phase's schema change (HOTELS_VECTOR no longer nested) exists to fix.
    assert query_filter.must[0].key == "destination_id"


@patch("src.services.hotel_search.get_qdrant_client")
@patch("src.services.hotel_search.get_embeddings")
def test_search_hotels_skips_stale_payload_version(mock_get_embeddings, mock_get_client):
    """A point with no/mismatched payload_version (Gen-1 nested shape, or a
    mid-migration read) must be skipped, not silently collapsed into a
    garbage result keyed 'None:None'."""
    mock_get_embeddings.return_value.embed_query.return_value = [0.1, 0.2]
    client = MagicMock()
    stale_payload = {"page_content": "...", "metadata": {"hotel_id": "abc"}}  # Gen-1 shape, no payload_version
    fresh_payload = _payload(source_hotel_id=1)
    client.query_points.return_value = MagicMock(
        points=[_point(stale_payload), _point(fresh_payload)]
    )
    mock_get_client.return_value = client

    results = search_hotels("hotel in Da Nang", k=5, use_llm_filter=False)

    assert len(results) == 1
    assert results[0]["matched_listing_ids"] == ["agoda:1"]


@patch("src.services.hotel_search.get_qdrant_client")
@patch("src.services.hotel_search.get_embeddings")
def test_search_hotels_sorted_by_score_and_carries_id(mock_get_embeddings, mock_get_client):
    mock_get_embeddings.return_value.embed_query.return_value = [0.1, 0.2]
    client = MagicMock()
    low_score_hit = _payload(source_hotel_id=1, supabase_hotel_id="sb-1")
    high_score_hit = _payload(source_hotel_id=2, supabase_hotel_id="sb-2")
    client.query_points.return_value = MagicMock(
        points=[_point(low_score_hit, score=0.4), _point(high_score_hit, score=0.9)]
    )
    mock_get_client.return_value = client

    results = search_hotels("hotel in Da Nang", k=5, use_llm_filter=False)

    assert [r["score"] for r in results] == [0.9, 0.4]
    assert results[0]["id"] == "sb-2"


@patch("src.services.hotel_search.get_qdrant_client")
@patch("src.services.hotel_search.get_embeddings")
def test_search_hotels_id_none_when_supabase_hotel_id_unresolved(mock_get_embeddings, mock_get_client):
    """Default state (sync_to_supabase off): every payload's
    supabase_hotel_id is None, so `id` must be None too, not raise or
    default to something misleading."""
    mock_get_embeddings.return_value.embed_query.return_value = [0.1, 0.2]
    client = MagicMock()
    client.query_points.return_value = MagicMock(points=[_point(_payload(source_hotel_id=1))])
    mock_get_client.return_value = client

    results = search_hotels("hotel in Da Nang", k=5, use_llm_filter=False)

    assert results[0]["id"] is None


@patch("src.services.hotel_search.get_qdrant_client")
@patch("src.services.hotel_search.get_embeddings")
@patch("src.services.hotel_search.extract_search_filters")
def test_search_hotels_llm_filter_cleans_query_and_extracts_destination(
    mock_extract_filters, mock_get_embeddings, mock_get_client
):
    mock_extract_filters.return_value = {
        "clean_query": "beachfront hotel",
        "destination_name": "Da Nang",
        "min_star_rating": 4,
    }
    mock_get_embeddings.return_value.embed_query.return_value = [0.1, 0.2]
    client = MagicMock()
    client.query_points.return_value = MagicMock(points=[])
    mock_get_client.return_value = client

    with patch(
        "src.services.supabase_search._get_destination_id_by_name",
        return_value="dest-resolved",
    ):
        search_hotels("beachfront hotel in Da Nang", k=5)

    mock_get_embeddings.return_value.embed_query.assert_called_once_with("beachfront hotel")
    _, kwargs = client.query_points.call_args
    assert kwargs["query_filter"].must[0].match.value == "dest-resolved"


@patch("src.services.hotel_search.get_qdrant_client")
@patch("src.services.hotel_search.get_embeddings")
def test_search_hotels_star_rating_filter_excludes_below_minimum(mock_get_embeddings, mock_get_client):
    mock_get_embeddings.return_value.embed_query.return_value = [0.1, 0.2]
    client = MagicMock()
    client.query_points.return_value = MagicMock(
        points=[
            _point(_payload(source_hotel_id=1, star_rating=3.0)),
            _point(_payload(source_hotel_id=2, star_rating=5.0)),
        ]
    )
    mock_get_client.return_value = client

    with patch(
        "src.services.hotel_search.extract_search_filters",
        return_value={"min_star_rating": 4},
    ):
        results = search_hotels("hotel in Da Nang", k=5, use_llm_filter=True)

    assert len(results) == 1
    assert results[0]["matched_listing_ids"] == ["agoda:2"]
