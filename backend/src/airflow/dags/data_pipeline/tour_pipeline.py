"""Tour/Activity data pipeline: Extract -> Validate -> Normalize -> Dedupe -> Load -> QualityCheck.

Loads Booking.com tour/activity data (fetched live from an Apify actor — see
`fetch_tours_from_apify` below and `tour_pipeline_dag.py`) into the flat
`tours` table, one row per `(source_platform, source_id)`; see
scripts/database_schema.sql.

Kept as its own module rather than folded into hotel_pipeline.py: tours share
almost no fields with hotels (a single flat record, no rooms/prices, USD
pricing, a free-form nested `itinerary` blob instead of structured rooms —
see hotel_pipeline.py's own docstring for why hotels are likewise kept
separate from the OSM/Google Maps attraction pipelines). Reuses
hotel_pipeline.normalize_city and .parse_datetime rather than duplicating
them, since city aliasing and ISO-datetime parsing are the same problem in
both domains; everything tour-specific (category mapping, ISO-8601 duration
parsing, the `tours` upsert) lives here.
"""

import json
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import psycopg2
from apify_client import ApifyClient
from psycopg2.extras import Json

from hotel_pipeline import normalize_city
from osm_pipeline import get_or_create_destination

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Reference data (source-specific text -> canonical value)
# ---------------------------------------------------------------------------

# Raw taxonomy_type (Booking tours) -> canonical category value. Booking
# sends inconsistent labels for the same thing depending on locale/endpoint.
BOOKING_TOUR_CATEGORY_MAP = {
    "tours": "Tours",
    "tour du lịch": "Tours",
}


def normalize_tour_category(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    key = raw.strip().casefold()
    return BOOKING_TOUR_CATEGORY_MAP.get(key, raw.strip())


# ---------------------------------------------------------------------------
# Extract
# ---------------------------------------------------------------------------

# Canonical source_platform vocabulary for tours. Only Booking ships
# tour/activity data through the Apify actor today; kept as an explicit set
# (mirrors hotel_pipeline.CANONICAL_SOURCE_PLATFORMS) so a second source
# can't silently mint a second vocabulary for the same field.
CANONICAL_TOUR_SOURCE_PLATFORMS = frozenset({"booking"})


def _nfc_deep(value: Any) -> Any:
    """Normalize every string to Unicode NFC.

    Booking ships NFD for at least `city_name` (precomposed vs. base letter +
    combining accent), same inconsistency hotel_pipeline._nfc_deep works
    around for hotel `city`. Left alone, casefold-equal strings compare
    unequal downstream (city alias matching, dedupe keys).
    """
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, list):
        return [_nfc_deep(v) for v in value]
    if isinstance(value, dict):
        return {
            (unicodedata.normalize("NFC", k) if isinstance(k, str) else k): _nfc_deep(v)
            for k, v in value.items()
        }
    return value


def extract_tours(records: List[Dict[str, Any]], source_platform: str) -> List[Dict[str, Any]]:
    """Tags already-fetched raw tour records (Apify dataset items, or a local
    JSON dump in tests) with `source_platform` and NFC-normalizes strings."""
    if source_platform not in CANONICAL_TOUR_SOURCE_PLATFORMS:
        raise ValueError(f"Unknown source_platform: {source_platform!r}")
    records = [_nfc_deep(record) for record in records]
    for record in records:
        record["source_platform"] = source_platform
    logger.info("extract: %s -> %d tour records", source_platform, len(records))
    return records


def extract_tours_from_file(path: str, source_platform: str = "booking") -> List[Dict[str, Any]]:
    """File-based extract for local testing/backfills, mirrors
    hotel_pipeline.extract_source. Production runs use
    fetch_tours_from_apify instead — see tour_pipeline_dag.py."""
    with Path(path).open(encoding="utf-8") as f:
        records = json.load(f)
    return extract_tours(records, source_platform)


def fetch_tours_from_apify(
    actor_id: str,
    source_platform: str,
    token: str,
    run_input: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Trigger a fresh Apify actor run and return its dataset items, tagged
    and NFC-normalized. Blocks until the run finishes — tour prices/
    availability change constantly, so a stale previous dataset isn't good
    enough; every pipeline run re-crawls."""
    client = ApifyClient(token)
    run = client.actor(actor_id).call(run_input=run_input or {})
    if run.get("status") != "SUCCEEDED":
        raise RuntimeError(
            f"Apify actor {actor_id} run {run.get('id')} ended with status {run.get('status')!r}"
        )

    records = list(client.dataset(run["defaultDatasetId"]).iterate_items())
    records = extract_tours(records, source_platform)
    logger.info(
        "extract: %s -> %d tour records from Apify actor %s (run %s)",
        source_platform, len(records), actor_id, run.get("id"),
    )
    return records


# ---------------------------------------------------------------------------
# Validate
# ---------------------------------------------------------------------------

@dataclass
class ValidationStats:
    total: int = 0
    valid: int = 0
    rejected: int = 0
    rejected_samples: List[str] = field(default_factory=list)


def _is_valid_raw_tour(record: Dict[str, Any]) -> Optional[str]:
    """Return an error message if invalid, None if valid.

    Must catch every condition that would otherwise violate a DB constraint
    at load time (tours.name NOT NULL) — the whole batch loads in one
    transaction, so a constraint violation here aborts every tour in the
    run, not just the offending record.
    """
    if not record.get("tour_id"):
        return f"tour_id missing or empty (got {record.get('tour_id')!r})"
    if not record.get("name"):
        return "name missing or empty"
    price = record.get("price")
    if price is not None and not isinstance(price, (int, float)):
        return f"price is not numeric (got {price!r})"
    return None


def validate_tours(raw_records: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], ValidationStats]:
    stats = ValidationStats(total=len(raw_records))
    validated: List[Dict[str, Any]] = []

    for record in raw_records:
        error = _is_valid_raw_tour(record)
        if error is None:
            validated.append(record)
            stats.valid += 1
        else:
            stats.rejected += 1
            msg = f"{record.get('source_platform', '?')}:{record.get('tour_id', '?')} -> {error}"
            stats.rejected_samples.append(msg)
            logger.warning("validate: rejected tour record %s", msg)

    logger.info("validate: %d/%d tour records passed (%d rejected)", stats.valid, stats.total, stats.rejected)
    return validated, stats


# ---------------------------------------------------------------------------
# Normalize
# ---------------------------------------------------------------------------

_ISO8601_DURATION_RE = re.compile(
    r"^P(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?$"
)


def parse_iso8601_duration_minutes(raw: Optional[str]) -> Optional[int]:
    """"PT10H" -> 600, "PT50M" -> 50. None when raw is None/unparseable/empty
    (Booking omits duration_iso when a tour has a variable duration range and
    only `duration_label` text is available).
    """
    if not raw:
        return None
    match = _ISO8601_DURATION_RE.match(raw.strip())
    if not match or not any(match.groupdict().values()):
        return None
    parts = {k: int(v or 0) for k, v in match.groupdict().items()}
    return parts["days"] * 24 * 60 + parts["hours"] * 60 + parts["minutes"] + parts["seconds"] // 60


def normalize_tour(raw: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "source_platform": raw["source_platform"],
        "source_id": raw["tour_id"],
        "source_url": raw.get("tour_url"),
        "name": raw["name"],
        "description": raw.get("description"),
        "category": normalize_tour_category(raw.get("taxonomy_type")),
        "duration_minutes": parse_iso8601_duration_minutes(raw.get("duration_iso")),
        "duration_label": raw.get("duration_label"),
        "price": raw.get("price"),
        "currency": raw.get("currency"),
        "rating": raw.get("review_score"),
        "review_count": raw.get("review_count"),
        "category_scores": raw.get("category_scores"),
        "has_free_cancellation": raw.get("has_free_cancellation"),
        "is_bookable": raw.get("is_bookable"),
        "whats_included": raw.get("whats_included") or [],
        "not_included": raw.get("not_included") or [],
        "highlights": raw.get("highlights") or [],
        "accessibility": raw.get("accessibility") or [],
        "restrictions": raw.get("restrictions") or [],
        "additional_info": raw.get("additional_info"),
        "image_url": raw.get("image_url"),
        "image_count": raw.get("image_count"),
        "images": raw.get("all_images") or [],
        "itinerary_details": raw.get("itinerary"),
        # Kept as the raw ISO-8601 string (not parsed to a datetime object):
        # this dict travels through Airflow XCom between tasks, and Postgres
        # casts a valid ISO-8601 string literal to TIMESTAMP on INSERT just
        # fine, so there's no need to risk a non-JSON-serializable value.
        "scraped_at": raw.get("scraped_at"),
        "destination_name": normalize_city(raw.get("city_name")),
    }


def normalize_tours(validated: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    records = [normalize_tour(raw) for raw in validated]
    logger.info("normalize: %d tours normalized", len(records))
    return records


# ---------------------------------------------------------------------------
# Deduplicate
# ---------------------------------------------------------------------------

@dataclass
class DedupeStats:
    tours_removed: int = 0


def _is_newer(candidate: Optional[str], current: Optional[str]) -> bool:
    if candidate is None:
        return False
    if current is None:
        return True
    return candidate > current


def dedupe_tours(tours: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], DedupeStats]:
    """Within-batch only, same reasoning as hotel_pipeline.dedupe_hotels: this
    does not merge tours across OTAs, only removes exact
    (source_platform, source_id) repeats within one run, newest scraped_at
    wins (plain string comparison — safe because scraped_at is always the
    same fixed-precision ISO-8601 format within one Apify run)."""
    stats = DedupeStats()
    by_key: Dict[Tuple[str, str], Dict[str, Any]] = {}

    for tour in tours:
        key = (tour["source_platform"], tour["source_id"])
        existing = by_key.get(key)
        if existing is None:
            by_key[key] = tour
            continue
        stats.tours_removed += 1
        if _is_newer(tour.get("scraped_at"), existing.get("scraped_at")):
            by_key[key] = tour

    deduped = list(by_key.values())
    logger.info("dedupe: removed %d duplicate tours", stats.tours_removed)
    return deduped, stats


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------

@dataclass
class LoadStats:
    tours_upserted: int = 0


_TOUR_COLUMNS = [
    "destination_id", "source_platform", "source_id", "source_url", "name", "description",
    "category", "duration_minutes", "duration_label", "price", "currency", "rating",
    "review_count", "category_scores", "has_free_cancellation", "is_bookable",
    "whats_included", "not_included", "highlights", "accessibility", "restrictions",
    "additional_info", "image_url", "image_count", "images", "itinerary_details", "scraped_at",
]

_TOUR_UPDATE_COLUMNS = [c for c in _TOUR_COLUMNS if c not in ("source_platform", "source_id")]

# category_scores/itinerary_details are JSONB; whats_included/not_included/highlights/
# accessibility/restrictions/images are native Postgres TEXT[] arrays and must NOT be
# wrapped in Json(), psycopg2 adapts Python lists of str to TEXT[] directly.
_ARRAY_JSONB_EXCEPTIONS = {
    "whats_included", "not_included", "highlights", "accessibility", "restrictions", "images",
}


def _jsonb_fields(row: Dict[str, Any], keys: List[str]) -> Dict[str, Any]:
    return {k: (Json(v) if isinstance(v, (dict, list)) and k not in _ARRAY_JSONB_EXCEPTIONS else v) for k, v in row.items() if k in keys}


def _upsert_tour(cursor, tour: Dict[str, Any], destination_id: Optional[str]) -> str:
    row = {**tour, "destination_id": destination_id}
    columns = _TOUR_COLUMNS
    values = _jsonb_fields(row, columns)
    placeholders = ", ".join(f"%({c})s" for c in columns)
    update_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in _TOUR_UPDATE_COLUMNS)
    query = f"""
        INSERT INTO tours ({", ".join(columns)})
        VALUES ({placeholders})
        ON CONFLICT (source_platform, source_id) DO UPDATE SET
            {update_clause},
            updated_at = CURRENT_TIMESTAMP
        RETURNING id;
    """
    cursor.execute(query, values)
    return str(cursor.fetchone()[0])


def load_tours_to_db(tours: List[Dict[str, Any]], db_conn_kwargs: Dict[str, str]) -> LoadStats:
    stats = LoadStats()
    conn = None
    cursor = None
    try:
        conn = psycopg2.connect(**db_conn_kwargs)
        cursor = conn.cursor()

        destination_ids: Dict[Optional[str], Optional[str]] = {}
        for tour in tours:
            destination_name = tour.get("destination_name")
            if destination_name not in destination_ids:
                destination_ids[destination_name] = (
                    get_or_create_destination(destination_name, "", db_conn_kwargs)
                    if destination_name
                    else None
                )
            destination_id = destination_ids[destination_name]

            _upsert_tour(cursor, {k: v for k, v in tour.items() if k != "destination_name"}, destination_id)
            stats.tours_upserted += 1

        conn.commit()
    except Exception as e:
        print(f"Database insertion error in load_tours_to_db: {e}")
        if conn:
            conn.rollback()
        raise e
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

    logger.info("load: upserted %d tours", stats.tours_upserted)
    return stats


# ---------------------------------------------------------------------------
# Quality Check
# ---------------------------------------------------------------------------

def _sanity_checks(tours: List[Dict[str, Any]]) -> List[str]:
    issues = []
    for tour in tours:
        label = f"{tour['source_platform']}:{tour['source_id']}"
        price = tour.get("price")
        if price is not None and price <= 0:
            issues.append(f"{label}: price <= 0 ({price})")
        if not tour.get("destination_name"):
            issues.append(f"{label}: could not resolve a destination from city_name")
    return issues


def quality_check_tours(
    validation_stats: ValidationStats,
    dedupe_stats: DedupeStats,
    load_stats: LoadStats,
    tours: List[Dict[str, Any]],
    reports_dir: str,
) -> str:
    import datetime as _datetime

    issues = _sanity_checks(tours)

    timestamp = _datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    reports_path = Path(reports_dir)
    reports_path.mkdir(parents=True, exist_ok=True)
    report_path = reports_path / f"tour_quality_report_{timestamp}.md"

    lines = [
        f"# Tour Pipeline Quality Report — {timestamp}",
        "",
        "## Validate & Clean",
        f"- Total extracted: {validation_stats.total}",
        f"- Passed validation: {validation_stats.valid}",
        f"- Rejected: {validation_stats.rejected}",
    ]
    if validation_stats.rejected_samples:
        lines.append("- Rejected samples:")
        lines += [f"  - {s}" for s in validation_stats.rejected_samples[:20]]

    lines += [
        "",
        "## Deduplicate (within-batch only, does not merge across OTAs)",
        f"- Duplicate tours removed: {dedupe_stats.tours_removed}",
        "",
        "## Load",
        f"- Tours upserted: {load_stats.tours_upserted}",
        "",
        "## Sanity check issues",
    ]
    if issues:
        lines += [f"- {issue}" for issue in issues[:50]]
        if len(issues) > 50:
            lines.append(f"- ... and {len(issues) - 50} more")
    else:
        lines.append("- None found")

    report_text = "\n".join(lines)
    report_path.write_text(report_text, encoding="utf-8")
    logger.info("quality_check: report written to %s", report_path)
    return str(report_path)


# ---------------------------------------------------------------------------
# End-to-end runner (standalone entrypoint, mirrors the Airflow task sequence)
# ---------------------------------------------------------------------------

def run_tour_pipeline(
    path: str,
    db_conn_kwargs: Dict[str, str],
    reports_dir: str,
    source_platform: str = "booking",
) -> str:
    raw_records = extract_tours_from_file(path, source_platform)
    validated, validation_stats = validate_tours(raw_records)
    normalized = normalize_tours(validated)
    deduped, dedupe_stats = dedupe_tours(normalized)
    load_stats = load_tours_to_db(deduped, db_conn_kwargs)
    return quality_check_tours(validation_stats, dedupe_stats, load_stats, deduped, reports_dir)
