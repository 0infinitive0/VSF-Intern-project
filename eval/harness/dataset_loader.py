"""Strict-schema loaders for the golden datasets. Rejects unknown fields,
missing rationale, malformed UUIDs, and duplicate ids - a silently-skipped
malformed row would quietly shrink the eval set.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID

from harness.turn_metrics import KNOWN_ANSWER_CHECKS

_DATASETS_DIR = Path(__file__).resolve().parent.parent / "datasets"

_RETRIEVAL_REQUIRED = {"id", "layer", "search", "language", "query", "expected_ids", "rationale"}
_RETRIEVAL_OPTIONAL = {"pair_id", "filters", "acceptable_ids", "notes", "llm_average_excluded"}
_RETRIEVAL_FIELDS = _RETRIEVAL_REQUIRED | _RETRIEVAL_OPTIONAL

_CONVERSATION_REQUIRED = {"id", "layer", "language", "turns", "expected_stage", "assertions"}
# `answer_checks` is the machine-checkable half of `assertions`: `[{"turn": 4, "kind":
# "lists_rooms_of_selected_hotel"}]` names a turn whose reply must actually carry the
# information its question asked for. Optional — a conversation without one is scored
# exactly as before.
_CONVERSATION_OPTIONAL = {"answer_checks"}
_CONVERSATION_FIELDS = _CONVERSATION_REQUIRED | _CONVERSATION_OPTIONAL

_VALID_SEARCH = {"hotels", "attractions"}
_VALID_LANGUAGE = {"vi", "en"}
# Mirrors `ChatStage` (backend/src/models/schemas.py) exactly. `finalized` and
# `modified` used to be here; both were dropped when the graph plane replaced the
# `process_chat_turn` cascade that was their only producer, so a record declaring one
# is unachievable by construction and would report as a failure that says nothing
# about agent quality. Two records did — see the 2026-08-18 adjudication in
# datasets/README.md. Rejecting the value here is what stops a third being written.
_VALID_STAGE = {"intake", "hotel_options", "planned", "error"}


class DatasetValidationError(ValueError):
    """A golden dataset record failed schema validation."""


@dataclass(frozen=True)
class RetrievalRecord:
    id: str
    layer: str
    search: str
    language: str
    query: str
    expected_ids: list[str]
    rationale: str
    pair_id: str | None = None
    filters: dict | None = None
    acceptable_ids: list[str] = field(default_factory=list)
    notes: str | None = None
    # True for a record whose low llm_precision/llm_context_relevance is a known,
    # separately-documented finding rather than something the headline average
    # should keep re-reporting: a deliberate negative-test probe (search SHOULD
    # find nothing, so a low score is correct behaviour, not a quality signal), or
    # a real, already-filed retriever gap (e.g. a brand-name query the search
    # cannot surface at all - see `rationale` for which). ADJUDICATED 2026-08-20,
    # user decision. Non-LLM precision/recall are unaffected - those are exact ID
    # comparisons and stay meaningful for every record regardless of this flag.
    llm_average_excluded: bool = False


@dataclass(frozen=True)
class ConversationRecord:
    id: str
    layer: str
    language: str
    turns: list[str]
    expected_stage: str
    assertions: list[str]
    #: `[{"turn": <1-based index>, "kind": <one of turn_metrics.KNOWN_ANSWER_CHECKS>}]`
    answer_checks: list[dict] = field(default_factory=list)


def _require_uuid(value: str, *, record_id: str, field_name: str) -> None:
    try:
        UUID(value)
    except (ValueError, AttributeError, TypeError) as exc:
        raise DatasetValidationError(
            f"{record_id}: {field_name} contains a malformed UUID: {value!r}"
        ) from exc


def _validate_retrieval_row(row: dict, *, line_no: int) -> RetrievalRecord:
    record_id = row.get("id", f"<line {line_no}>")

    unknown = set(row) - _RETRIEVAL_FIELDS
    if unknown:
        raise DatasetValidationError(f"{record_id}: unknown field(s) {sorted(unknown)}")
    missing = _RETRIEVAL_REQUIRED - set(row)
    if missing:
        raise DatasetValidationError(f"{record_id}: missing required field(s) {sorted(missing)}")

    if not row["id"] or not isinstance(row["id"], str):
        raise DatasetValidationError(f"line {line_no}: id must be a non-empty string")
    if row["layer"] != "retrieval":
        raise DatasetValidationError(f"{record_id}: layer must be 'retrieval', got {row['layer']!r}")
    if row["search"] not in _VALID_SEARCH:
        raise DatasetValidationError(f"{record_id}: search must be one of {_VALID_SEARCH}, got {row['search']!r}")
    if row["language"] not in _VALID_LANGUAGE:
        raise DatasetValidationError(f"{record_id}: language must be one of {_VALID_LANGUAGE}, got {row['language']!r}")
    if not row["query"] or not isinstance(row["query"], str):
        raise DatasetValidationError(f"{record_id}: query must be a non-empty string")
    if not row.get("rationale", "").strip():
        raise DatasetValidationError(f"{record_id}: rationale must be non-empty")
    if not isinstance(row["expected_ids"], list):
        raise DatasetValidationError(f"{record_id}: expected_ids must be a list")
    acceptable_ids = row.get("acceptable_ids", [])
    if not isinstance(acceptable_ids, list):
        raise DatasetValidationError(f"{record_id}: acceptable_ids must be a list")

    for pid in row["expected_ids"] + acceptable_ids:
        _require_uuid(pid, record_id=record_id, field_name="expected_ids/acceptable_ids")

    llm_average_excluded = row.get("llm_average_excluded", False)
    if not isinstance(llm_average_excluded, bool):
        raise DatasetValidationError(f"{record_id}: llm_average_excluded must be a bool")

    return RetrievalRecord(
        id=row["id"],
        layer=row["layer"],
        search=row["search"],
        language=row["language"],
        query=row["query"],
        expected_ids=row["expected_ids"],
        rationale=row["rationale"],
        pair_id=row.get("pair_id"),
        filters=row.get("filters"),
        acceptable_ids=acceptable_ids,
        notes=row.get("notes"),
        llm_average_excluded=llm_average_excluded,
    )


def _validate_conversation_row(row: dict, *, line_no: int) -> ConversationRecord:
    record_id = row.get("id", f"<line {line_no}>")

    unknown = set(row) - _CONVERSATION_FIELDS
    if unknown:
        raise DatasetValidationError(f"{record_id}: unknown field(s) {sorted(unknown)}")
    missing = _CONVERSATION_REQUIRED - set(row)
    if missing:
        raise DatasetValidationError(f"{record_id}: missing required field(s) {sorted(missing)}")

    if not row["id"] or not isinstance(row["id"], str):
        raise DatasetValidationError(f"line {line_no}: id must be a non-empty string")
    if row["layer"] != "e2e":
        raise DatasetValidationError(f"{record_id}: layer must be 'e2e', got {row['layer']!r}")
    if row["language"] not in _VALID_LANGUAGE:
        raise DatasetValidationError(f"{record_id}: language must be one of {_VALID_LANGUAGE}, got {row['language']!r}")
    if not isinstance(row["turns"], list) or not row["turns"]:
        raise DatasetValidationError(f"{record_id}: turns must be a non-empty list")
    if not all(isinstance(t, str) and t.strip() for t in row["turns"]):
        raise DatasetValidationError(f"{record_id}: every turn must be a non-empty string")
    if row["expected_stage"] not in _VALID_STAGE:
        raise DatasetValidationError(
            f"{record_id}: expected_stage must be one of {_VALID_STAGE}, got {row['expected_stage']!r}"
        )
    if not isinstance(row["assertions"], list) or not row["assertions"]:
        raise DatasetValidationError(f"{record_id}: assertions must be a non-empty list")

    checks = row.get("answer_checks") or []
    if not isinstance(checks, list):
        raise DatasetValidationError(f"{record_id}: answer_checks must be a list")
    for check in checks:
        # Validated here rather than at replay time: a typo'd `kind` or an off-the-end
        # `turn` would otherwise be a check that silently never runs, which reads
        # exactly like a check that ran and passed.
        if not isinstance(check, dict) or set(check) != {"turn", "kind"}:
            raise DatasetValidationError(
                f"{record_id}: every answer_check needs exactly the keys turn and kind, got {check!r}"
            )
        if check["kind"] not in KNOWN_ANSWER_CHECKS:
            raise DatasetValidationError(
                f"{record_id}: unknown answer_check kind {check['kind']!r}, "
                f"expected one of {sorted(KNOWN_ANSWER_CHECKS)}"
            )
        if not isinstance(check["turn"], int) or not 1 <= check["turn"] <= len(row["turns"]):
            raise DatasetValidationError(
                f"{record_id}: answer_check turn {check['turn']!r} is outside this "
                f"conversation's {len(row['turns'])} turn(s)"
            )

    return ConversationRecord(
        id=row["id"],
        layer=row["layer"],
        language=row["language"],
        turns=row["turns"],
        expected_stage=row["expected_stage"],
        assertions=row["assertions"],
        answer_checks=checks,
    )


def _load_jsonl(path: Path, validator) -> list:
    records = []
    seen_ids: set[str] = set()
    with open(path, encoding="utf-8") as f:
        for line_no, raw_line in enumerate(f, start=1):
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                row = json.loads(raw_line)
            except json.JSONDecodeError as exc:
                raise DatasetValidationError(f"{path.name}:{line_no}: invalid JSON: {exc}") from exc
            record = validator(row, line_no=line_no)
            if record.id in seen_ids:
                raise DatasetValidationError(f"{path.name}:{line_no}: duplicate id {record.id!r}")
            seen_ids.add(record.id)
            records.append(record)
    return records


#: Record counts a default (Vietnamese-only) load must produce. Asserted rather than
#: trusted: a filter that over-matches shrinks the eval set silently, and a smaller
#: set reports as *better* scores, never as an error. These numbers change only when
#: a record is genuinely added or removed from a `.jsonl` - most recently 2026-08-20
#: (user decision), in two passes: (1) 3 negative-test probes and one already-filed
#: retriever-gap probe (`hotel-crosslang-libertycentral-vi`) removed, 30 -> 26; (2)
#: `hotel-hue-thin-vi` (deliberate thin-corpus probe), `hotel-hcm-family-vi` and
#: `attraction-hue-citadel-vi` (both already-filed retriever gaps) removed, 26 -> 23
#: — `attraction-hue-citadel-en`, its EN pair, was deleted alongside it: leaving an
#: EN mirror with no vi partner would have made `_is_en_mirror` stop recognising it,
#: leaking an English record into the "Vietnamese-only" set.
_EXPECTED_VI_RETRIEVAL = 23
_EXPECTED_VI_CONVERSATIONS = 9


def _is_en_mirror(record: RetrievalRecord, records: list[RetrievalRecord]) -> bool:
    """An EN mirror is a straight translation of a VI record, and the two share a
    `pair_id` ("khách sạn ở Nha Trang" / "a hotel in Nha Trang").

    The predicate keys off **pair partnership, not the `language` field**, and that
    distinction is the whole design. The `hotel-crosslang-*` probes are not mirrors:
    each holds a `pair_id` with no partner, and two of them are labelled `en` because
    they run an EN sentence carrying a VI brand name ("find me a room at Khách Sạn
    Mường Thanh Luxury"). They test BR-10 — a mixed-language query, which is a
    Vietnamese-user scenario — so they stay in scope. Filtering on `language == "en"`
    would delete half of BR-10's only evidence as collateral damage, and it would do
    it silently.
    """
    if record.language != "en" or not record.pair_id:
        return False
    return any(other.pair_id == record.pair_id and other.language == "vi" for other in records)


def load_golden_retrieval(
    path: Path | None = None, *, include_en_mirrors: bool = False
) -> list[RetrievalRecord]:
    """Vietnamese-only by default; `include_en_mirrors=True` restores the full 36.

    The excluded EN-mirror records stay in the `.jsonl` — this filters, it never
    deletes them. They carry a rewritten-rationale pass that would be an authoring
    job to recreate. (Separately, 4 non-mirror records were deleted outright on
    2026-08-20 — see `_EXPECTED_VI_RETRIEVAL`'s comment.)
    """
    records = _load_jsonl(path or _DATASETS_DIR / "golden-retrieval.jsonl", _validate_retrieval_row)
    if include_en_mirrors:
        return records

    kept = [r for r in records if not _is_en_mirror(r, records)]
    if path is None and len(kept) != _EXPECTED_VI_RETRIEVAL:
        raise DatasetValidationError(
            f"EN-mirror filter kept {len(kept)} retrieval records, expected {_EXPECTED_VI_RETRIEVAL}. "
            "Either a record was added/removed, or the filter is over-matching — check that all "
            "hotel-crosslang-* probes survived before updating this count."
        )
    return kept


def load_golden_conversations(
    path: Path | None = None, *, include_en_mirrors: bool = False
) -> list[ConversationRecord]:
    """Vietnamese-only by default; `include_en_mirrors=True` restores the full 10.

    Conversations carry no `pair_id`, so there is no mirror structure to key off —
    `conv-hcm-luxury-en` is simply the suite's one English conversation. The count
    assertion below is what guards this cruder predicate: a mixed-language
    conversation added later and labelled `en` would be dropped by it, and the
    changed count is what surfaces that rather than letting it pass unnoticed.
    """
    records = _load_jsonl(
        path or _DATASETS_DIR / "golden-conversations.jsonl", _validate_conversation_row
    )
    if include_en_mirrors:
        return records

    kept = [r for r in records if r.language != "en"]
    if path is None and len(kept) != _EXPECTED_VI_CONVERSATIONS:
        raise DatasetValidationError(
            f"EN filter kept {len(kept)} conversations, expected {_EXPECTED_VI_CONVERSATIONS}."
        )
    return kept


def retrieval_records_by_search(records: list[RetrievalRecord], search: str) -> list[RetrievalRecord]:
    return [r for r in records if r.search == search]


def retrieval_records_by_pair_id(records: list[RetrievalRecord]) -> dict[str, list[RetrievalRecord]]:
    """Group cross-language pairs. Records with no pair_id are excluded."""
    grouped: dict[str, list[RetrievalRecord]] = {}
    for r in records:
        if r.pair_id:
            grouped.setdefault(r.pair_id, []).append(r)
    return grouped


if __name__ == "__main__":
    retrieval = load_golden_retrieval()
    conversations = load_golden_conversations()
    print(f"golden-retrieval.jsonl: {len(retrieval)} valid records")
    print(f"golden-conversations.jsonl: {len(conversations)} valid records")
