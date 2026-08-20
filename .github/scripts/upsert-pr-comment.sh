#!/usr/bin/env bash
# Publishes a review file as a single PR comment, keyed by a hidden HTML marker.
# Re-running updates the existing comment instead of appending a new one, so a
# PR with many pushes keeps exactly one comment per reviewing agent.
#
# Usage: MARKER=... PR=... GH_REPO=... GH_TOKEN=... upsert-pr-comment.sh <file>
set -euo pipefail

review_file="${1:?usage: upsert-pr-comment.sh <review-file>}"
: "${MARKER:?MARKER is required}"
: "${PR:?PR is required}"

# The agent failed or produced nothing — leave any previous comment untouched
# rather than replacing it with an empty body.
if [[ ! -s "$review_file" ]]; then
  echo "No review content at $review_file; nothing to publish."
  exit 0
fi

body_file="$(mktemp)"
{
  printf '%s\n\n' "$MARKER"
  cat "$review_file"
} >"$body_file"

comment_id="$(
  gh api --paginate "repos/${GH_REPO}/issues/${PR}/comments" \
    --jq "[.[] | select(.body | startswith(\"${MARKER}\"))] | last | .id // empty"
)"

if [[ -n "$comment_id" ]]; then
  gh api -X PATCH "repos/${GH_REPO}/issues/comments/${comment_id}" -F "body=@${body_file}"
  echo "Updated comment ${comment_id}."
else
  gh api -X POST "repos/${GH_REPO}/issues/${PR}/comments" -F "body=@${body_file}"
  echo "Created new comment."
fi
