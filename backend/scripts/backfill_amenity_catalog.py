"""Resumable one-time conversion of raw amenity text arrays to catalog IDs.

Run from ``backend``:
    python scripts/backfill_amenity_catalog.py --table all --dry-run
    python scripts/backfill_amenity_catalog.py --table all --resume
"""

from __future__ import annotations

import argparse
import json
import signal
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.services.amenity_catalog import bind_amenity_rows
from src.services.supabase_search import get_supabase_client

CHECKPOINT_VERSION = 2
DEFAULT_PAGE_SIZE = 100
CATALOG_ONLY_BATCH_SIZE = 8
DEFAULT_CHECKPOINT = Path(__file__).resolve().parents[1] / "scratch" / "amenity_catalog_backfill.json"
TABLES = {
    "hotels": ("amenities", "hotel"),
    "rooms": ("room_facilities", "room"),
}
_STOP_REQUESTED = False


def _request_stop(_signum: int, _frame: object) -> None:
    global _STOP_REQUESTED
    _STOP_REQUESTED = True


def _new_checkpoint(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "version": CHECKPOINT_VERSION,
        "table": args.table,
        "page_size": args.page_size,
        "max_rows": args.max_rows,
        "only_id": args.only_id,
        "dry_run": args.dry_run,
        "catalog_only": args.catalog_only,
        "tables": {name: {"last_id": None, "completed": False} for name in _selected_tables(args.table)},
        "counts": {"processed": 0, "updated": 0, "unchanged": 0, "failed": 0, "catalog_added": 0},
        "failures": [],
        "proposals": [],
        "completed": False,
        "updated_at": _now(),
    }


def _load_checkpoint(path: Path, args: argparse.Namespace) -> dict[str, Any]:
    checkpoint = json.loads(path.read_text(encoding="utf-8"))
    expected = {
        "version": CHECKPOINT_VERSION,
        "table": args.table,
        "page_size": args.page_size,
        "max_rows": args.max_rows,
        "only_id": args.only_id,
        "dry_run": args.dry_run,
        "catalog_only": args.catalog_only,
    }
    if any(checkpoint.get(key) != value for key, value in expected.items()):
        raise ValueError("Checkpoint options do not match this command. Use the original options or --reset-checkpoint.")
    if checkpoint.get("completed"):
        raise ValueError("Checkpoint is complete. Use --reset-checkpoint before a new run.")
    return checkpoint


def _write_checkpoint(path: Path, checkpoint: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint["updated_at"] = _now()
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(checkpoint, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temp_path = Path(handle.name)
    temp_path.replace(path)


def _selected_tables(selection: str) -> tuple[str, ...]:
    return tuple(TABLES) if selection == "all" else (selection,)


def _fetch_page(
    client: Any, table: str, column: str, after_id: str | None, page_size: int, only_id: str | None
) -> list[dict[str, Any]]:
    if only_id and after_id:
        return []
    query = client.table(table).select(f"id,{column}").order("id").limit(page_size)
    if only_id:
        query = query.eq("id", only_id)
    elif after_id:
        query = query.gt("id", after_id)
    return list(getattr(query.execute(), "data", None) or [])


def _bar(checkpoint: dict[str, Any], table: str, page: int, started_at: float) -> str:
    counts = checkpoint["counts"]
    elapsed = int(time.monotonic() - started_at)
    return (
        f"[{table} page {page}] processed={counts['processed']} updated={counts['updated']} "
        f"unchanged={counts['unchanged']} failed={counts['failed']} catalog+={counts['catalog_added']} elapsed={elapsed}s"
    )


def _collect_catalog_values(client: Any, table: str, column: str, only_id: str | None) -> list[str]:
    values: set[str] = set()
    last_id: str | None = None
    while True:
        rows = _fetch_page(client, table, column, last_id, 1_000, only_id)
        if not rows:
            break
        for row in rows:
            values.update(value.strip() for value in row.get(column) or [] if isinstance(value, str) and value.strip())
        if only_id or len(rows) < 1_000:
            break
        last_id = rows[-1]["id"]
    return sorted(values)


def _run_catalog_only(
    args: argparse.Namespace, checkpoint_path: Path, checkpoint: dict[str, Any], client: Any, started_at: float
) -> int:
    catalog_values = checkpoint.setdefault("catalog_values", {})
    run_processed = 0
    for table in _selected_tables(args.table):
        if checkpoint["tables"][table]["completed"]:
            continue
        column, scope = TABLES[table]
        state = catalog_values.setdefault(table, {"values": _collect_catalog_values(client, table, column, args.only_id), "next_index": 0})
        values = state["values"]
        page = 0
        while state["next_index"] < len(values) and not _STOP_REQUESTED:
            if args.max_rows is not None and run_processed >= args.max_rows:
                _write_checkpoint(checkpoint_path, checkpoint)
                print(f"Stopped after --max-rows {args.max_rows}. Resume with --resume to continue.")
                return 0
            batch = values[state["next_index"]:state["next_index"] + CATALOG_ONLY_BATCH_SIZE]
            if args.max_rows is not None:
                batch = batch[:args.max_rows - run_processed]
            result = bind_amenity_rows([batch], scope=scope, persist=not args.dry_run)[0]
            page += 1
            checkpoint["counts"]["processed"] += len(batch)
            run_processed += len(batch)
            checkpoint["counts"]["catalog_added"] += len({proposal.id for proposal in result.proposals})
            checkpoint["counts"]["unchanged"] += len(batch) - len(result.unresolved)
            if result.unresolved:
                checkpoint["counts"]["failed"] += len(result.unresolved)
                checkpoint["failures"].append({"table": table, "id": f"catalog:{state['next_index']}", "values": list(result.unresolved)})
            state["next_index"] += len(batch)
            _write_checkpoint(checkpoint_path, checkpoint)
            print("\r" + _bar(checkpoint, table, page, started_at), end="", flush=True)
        print()
        if _STOP_REQUESTED:
            _write_checkpoint(checkpoint_path, checkpoint)
            print(f"Paused. Resume with: python scripts/backfill_amenity_catalog.py --table {args.table} --page-size {args.page_size} --checkpoint {checkpoint_path} --resume --catalog-only" + (" --dry-run" if args.dry_run else ""))
            return 130
        checkpoint["tables"][table]["completed"] = True
        _write_checkpoint(checkpoint_path, checkpoint)
    checkpoint["completed"] = True
    _write_checkpoint(checkpoint_path, checkpoint)
    print("Completed: " + _terminal_json(checkpoint["counts"]))
    return 0


def run(args: argparse.Namespace) -> int:
    checkpoint_path = Path(args.checkpoint)
    if args.reset_checkpoint and checkpoint_path.exists():
        checkpoint_path.unlink()
    if args.resume:
        if not checkpoint_path.exists():
            raise ValueError(f"Checkpoint does not exist: {checkpoint_path}")
        checkpoint = _load_checkpoint(checkpoint_path, args)
    else:
        if checkpoint_path.exists():
            raise ValueError(f"Checkpoint already exists: {checkpoint_path}. Use --resume or --reset-checkpoint.")
        checkpoint = _new_checkpoint(args)

    client = get_supabase_client()
    started_at = time.monotonic()
    if args.catalog_only:
        return _run_catalog_only(args, checkpoint_path, checkpoint, client, started_at)
    run_processed = 0
    for table in _selected_tables(args.table):
        if checkpoint["tables"][table]["completed"]:
            continue
        column, scope = TABLES[table]
        page = 0
        while not _STOP_REQUESTED:
            rows = _fetch_page(
                client, table, column, checkpoint["tables"][table]["last_id"], args.page_size, args.only_id
            )
            if not rows:
                checkpoint["tables"][table]["completed"] = True
                _write_checkpoint(checkpoint_path, checkpoint)
                break
            if args.max_rows is not None:
                remaining = args.max_rows - run_processed
                if remaining <= 0:
                    _write_checkpoint(checkpoint_path, checkpoint)
                    print(f"Stopped after --max-rows {args.max_rows}. Resume with --resume to continue.")
                    return 0
                rows = rows[:remaining]
            page += 1
            results = bind_amenity_rows(
                [row.get(column) or [] for row in rows], scope=scope, persist=not args.dry_run
            )
            page_catalog_additions = {
                proposal.id for result in results for proposal in result.proposals
            }
            checkpoint["counts"]["catalog_added"] += len(page_catalog_additions)
            for row, result in zip(rows, results, strict=True):
                raw_values = row.get(column) or []
                checkpoint["counts"]["processed"] += 1
                run_processed += 1
                if args.dry_run and result.proposals:
                    checkpoint["proposals"].append({
                        "table": table,
                        "id": row["id"],
                        "source_values": list(raw_values),
                        "catalog_rows": [_proposal_row(entry) for entry in result.proposals],
                    })
                if result.unresolved:
                    checkpoint["counts"]["failed"] += 1
                    checkpoint["failures"].append({"table": table, "id": row["id"], "values": list(result.unresolved)})
                elif args.catalog_only:
                    checkpoint["counts"]["unchanged"] += 1
                elif list(result.ids) == raw_values:
                    checkpoint["counts"]["unchanged"] += 1
                else:
                    checkpoint["counts"]["updated"] += 1
                    if not args.dry_run:
                        client.table(table).update({column: list(result.ids)}).eq("id", row["id"]).execute()
                checkpoint["tables"][table]["last_id"] = row["id"]
            _write_checkpoint(checkpoint_path, checkpoint)
            print("\r" + _bar(checkpoint, table, page, started_at), end="", flush=True)
        print()
        if _STOP_REQUESTED:
            _write_checkpoint(checkpoint_path, checkpoint)
            print(f"Paused. Resume with: python scripts/backfill_amenity_catalog.py --table {args.table} --page-size {args.page_size} --checkpoint {checkpoint_path} --resume" + (" --dry-run" if args.dry_run else ""))
            return 130
    checkpoint["completed"] = True
    _write_checkpoint(checkpoint_path, checkpoint)
    print("Completed: " + _terminal_json(checkpoint["counts"]))
    if args.dry_run and checkpoint["proposals"]:
        print("Proposed catalog rows: " + _terminal_json(checkpoint["proposals"], indent=2))
    return 0


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _proposal_row(entry: Any) -> dict[str, Any]:
    return {
        "id": entry.id,
        "label_vi": entry.label,
        "label_en": entry.label_en,
        "scope": entry.scope,
        "category": entry.category,
        "icon_key": entry.icon_key,
        "match_keywords": list(entry.match_keywords),
    }


def _terminal_json(value: object, *, indent: int | None = None, encoding: str | None = None) -> str:
    terminal_encoding = (encoding or sys.stdout.encoding or "utf-8").replace("-", "").lower()
    return json.dumps(value, ensure_ascii=terminal_encoding != "utf8", indent=indent)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--table", choices=(*TABLES, "all"), default="all")
    parser.add_argument("--page-size", type=int, default=DEFAULT_PAGE_SIZE)
    parser.add_argument("--max-rows", type=int, help="Stop after this many rows; checkpoint remains resumable.")
    parser.add_argument("--only-id", help="Process one explicit row ID (requires --table hotels or rooms).")
    parser.add_argument("--checkpoint", default=str(DEFAULT_CHECKPOINT))
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--catalog-only", action="store_true",
        help="Resolve and persist catalog entries/aliases without changing hotel or room arrays.",
    )
    parser.add_argument("--reset-checkpoint", action="store_true")
    args = parser.parse_args()
    if args.page_size < 1 or args.page_size > 1_000:
        parser.error("--page-size must be between 1 and 1000")
    if args.max_rows is not None and args.max_rows < 1:
        parser.error("--max-rows must be at least 1")
    if args.only_id and args.table == "all":
        parser.error("--only-id requires --table hotels or --table rooms")
    signal.signal(signal.SIGINT, _request_stop)
    try:
        return run(args)
    except (OSError, ValueError) as exc:
        print(f"Backfill failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
