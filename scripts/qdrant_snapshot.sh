#!/bin/bash
# Qdrant collection snapshot/restore (Phase 6). Run from the host — the
# local dev Qdrant is loopback-bound (127.0.0.1:6333), and its own image has
# no curl (verified: Debian trixie, bash only), so this can't run inside the
# qdrant container itself.
#
# Deliberately not scheduled: the hotel corpus rebuilds from Supabase through
# hotel_dag in minutes (Phase 5), so a manual pre-change snapshot is
# proportionate. Scheduling belongs in a deployment plan.
#
# Usage:
#   scripts/qdrant_snapshot.sh create <collection_name>
#   scripts/qdrant_snapshot.sh restore <snapshot_file> <target_collection_name>
#   scripts/qdrant_snapshot.sh list <collection_name>

set -euo pipefail

QDRANT_URL="${QDRANT_URL:-http://localhost:6333}"
SNAPSHOT_DIR="${QDRANT_SNAPSHOT_DIR:-./data/qdrant_snapshots}"

if [[ -z "${QDRANT_API_KEY:-}" ]]; then
  echo "ERROR: QDRANT_API_KEY must be set in the environment (see .env)." >&2
  exit 1
fi

auth_header=(-H "api-key: ${QDRANT_API_KEY}")

usage() {
  echo "Usage:"
  echo "  $0 create <collection_name>"
  echo "  $0 restore <snapshot_file> <target_collection_name>"
  echo "  $0 list <collection_name>"
  exit 1
}

cmd="${1:-}"

case "$cmd" in
  create)
    collection="${2:?collection_name required}"
    mkdir -p "$SNAPSHOT_DIR"
    echo "Creating snapshot of '${collection}'..."
    response=$(curl -sf -X POST "${auth_header[@]}" "${QDRANT_URL}/collections/${collection}/snapshots")
    snapshot_name=$(python3 -c "import sys, json; print(json.load(sys.stdin)['result']['name'])" <<<"$response")
    echo "Snapshot created: ${snapshot_name}"

    out_file="${SNAPSHOT_DIR}/${snapshot_name}"
    echo "Downloading to ${out_file}..."
    curl -sf "${auth_header[@]}" -o "$out_file" \
      "${QDRANT_URL}/collections/${collection}/snapshots/${snapshot_name}"
    echo "Saved: ${out_file}"
    ;;

  restore)
    snapshot_file="${2:?snapshot_file required}"
    target_collection="${3:?target_collection_name required}"
    if [[ ! -f "$snapshot_file" ]]; then
      echo "ERROR: snapshot file not found: ${snapshot_file}" >&2
      exit 1
    fi
    echo "Restoring ${snapshot_file} into '${target_collection}' (created if absent)..."
    curl -sf -X POST "${auth_header[@]}" \
      -F "snapshot=@${snapshot_file}" \
      "${QDRANT_URL}/collections/${target_collection}/snapshots/upload?priority=snapshot"
    echo
    echo "Restore submitted. Verify with:"
    echo "  curl -s -H \"api-key: \$QDRANT_API_KEY\" ${QDRANT_URL}/collections/${target_collection} | python3 -m json.tool"
    ;;

  list)
    collection="${2:?collection_name required}"
    curl -sf "${auth_header[@]}" "${QDRANT_URL}/collections/${collection}/snapshots" | python3 -m json.tool
    ;;

  *)
    usage
    ;;
esac
