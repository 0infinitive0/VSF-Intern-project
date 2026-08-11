"""Strict-schema loaders for the golden datasets. Rejects unknown fields,
missing rationale, malformed UUIDs, and duplicate ids - a silently-skipped
malformed row would quietly shrink the eval set.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID

_DATASETS_DIR = Path(__file__).resolve().parent.parent / "datasets"

_RETRIEVAL_REQUIRED = {"id", "layer", "search", "language", "query", "expected_ids", "rationale"}
_RETRIEVAL_OPTIONAL = {"pair_id", "filters", "acceptable_ids", "notes"}
_RETRIEVAL_FIELDS = _RETRIEVAL_REQUIRED | _RETRIEVAL_OPTIONAL

_CONVERSATION_REQUIRED = {"id", "layer", "language", "turns", "expected_stage", "assertions"}
_CONVERSATION_FIELDS = _CONVERSATION_REQUIRED

_VALID_SEARCH = {"hotels", "attractions"}
_VALID_LANGUAGE = {"vi", "en"}
_VALID_STAGE = {"intake", "hotel_options", "planned", "modified", "finalized", "error"}


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


@dataclass(frozen=True)
class ConversationRecord:
    id: str
    layer: str
    language: str
    turns: list[str]
    expected_stage: str
    assertions: list[str]


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

    return ConversationRecord(
        id=row["id"],
        layer=row["layer"],
        language=row["language"],
        turns=row["turns"],
        expected_stage=row["expected_stage"],
        assertions=row["assertions"],
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


def load_golden_retrieval(path: Path | None = None) -> list[RetrievalRecord]:
    return _load_jsonl(path or _DATASETS_DIR / "golden-retrieval.jsonl", _validate_retrieval_row)


def load_golden_conversations(path: Path | None = None) -> list[ConversationRecord]:
    return _load_jsonl(path or _DATASETS_DIR / "golden-conversations.jsonl", _validate_conversation_row)


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
