#!/usr/bin/env bash
# Resolve the git SHA to diff against for deploy-scope detection.
#
# Push: previous tip (github.event.before), unless it is missing/zero (new branch).
# Dispatch / missing before: last successful run of this workflow on this branch.
# Fallback: merge-base with the environment default branch.
# If nothing can be resolved, base_resolved=false (caller should deploy all lanes).
#
# Usage: ci-resolve-deploy-base.sh <event_name> <before_sha> <workflow_file> <branch> <default_base_ref>
# Writes base_sha / base_resolved / base_source to GITHUB_OUTPUT.
set -euo pipefail

EVENT_NAME="${1:?event name required}"
BEFORE_SHA="${2:-}"
WORKFLOW_FILE="${3:?workflow file required}"
BRANCH="${4:?branch required}"
DEFAULT_BASE_REF="${5:?default base ref required}"
CURRENT_SHA="${GITHUB_SHA:?GITHUB_SHA required}"
CURRENT_RUN_ID="${GITHUB_RUN_ID:-}"

is_usable_sha() {
  local sha="${1:-}"
  [[ "$sha" =~ ^[0-9a-fA-F]{7,40}$ ]] || return 1
  [[ "$sha" != "0000000000000000000000000000000000000000" ]] || return 1
  git cat-file -e "${sha}^{commit}" 2>/dev/null
}

write_outputs() {
  local sha="${1:-}"
  local source="${2:-none}"
  local resolved="false"
  if [ -n "$sha" ]; then
    resolved="true"
  fi
  {
    echo "base_sha=${sha}"
    echo "base_resolved=${resolved}"
    echo "base_source=${source}"
  } >> "${GITHUB_OUTPUT:?GITHUB_OUTPUT not set}"
  echo "Deploy change base: resolved=${resolved} source=${source} sha=${sha:-n/a}"
}

BASE=""
SOURCE=""

if [ "$EVENT_NAME" = "push" ] && is_usable_sha "$BEFORE_SHA"; then
  BASE="$BEFORE_SHA"
  SOURCE="push_before"
fi

if [ -z "$BASE" ] && command -v gh >/dev/null 2>&1; then
  RUNS_JSON="$(
    gh run list \
      --workflow "$WORKFLOW_FILE" \
      --branch "$BRANCH" \
      --status success \
      --limit 30 \
      --json headSha,databaseId,conclusion \
      2>/dev/null || true
  )"
  if echo "${RUNS_JSON:-}" | jq -e 'type == "array" and length > 0' >/dev/null 2>&1; then
    CANDIDATES="$(
      echo "$RUNS_JSON" | jq -r \
        --arg sha "$CURRENT_SHA" \
        --arg id "${CURRENT_RUN_ID:-}" '
          .[]
          | select(.conclusion == "success")
          | select((.headSha | tostring) != $sha)
          | select((.databaseId | tostring) != $id)
          | .headSha
        '
    )"
    while IFS= read -r candidate; do
      [ -n "$candidate" ] || continue
      if is_usable_sha "$candidate"; then
        BASE="$candidate"
        SOURCE="last_success"
        break
      fi
    done <<< "$CANDIDATES"
  fi
fi

if [ -z "$BASE" ]; then
  if [[ "$DEFAULT_BASE_REF" == origin/* ]]; then
    remote_branch="${DEFAULT_BASE_REF#origin/}"
    git fetch --no-tags origin "${remote_branch}:refs/remotes/origin/${remote_branch}" 2>/dev/null || true
  fi
  if git rev-parse --verify "$DEFAULT_BASE_REF" >/dev/null 2>&1; then
    MERGE_BASE="$(git merge-base "$CURRENT_SHA" "$DEFAULT_BASE_REF" 2>/dev/null || true)"
    if is_usable_sha "$MERGE_BASE"; then
      BASE="$MERGE_BASE"
      SOURCE="merge_base"
    fi
  fi
fi

write_outputs "$BASE" "${SOURCE:-none}"
