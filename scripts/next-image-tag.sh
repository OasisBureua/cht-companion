#!/usr/bin/env bash
# Compute the next semver ECR tag for CHT images.
# Dev: 1.0.0, 1.0.1, … (cht-dev-* repos)
# Platform: v1.0.0, v1.0.1, … (cht-platform-* repos)
# Ignores floating tags (dev-latest, prod-latest, sha tags, etc.).
#
# Each major/minor/patch segment is 0–9. Bumping past .9 rolls the next segment:
#   4.1.8 → 4.1.9 → 4.2.0
#   4.9.9 → 5.0.0
#
# When ECR is empty (or only has floating tags), falls back to the semver tag on the
# live ECS task definition so clearing ECR does not reuse a tag Terraform already has.
#
# Usage:
#   ./scripts/next-image-tag.sh [ECR_REPO] [AWS_REGION] [PREFIX] [ECS_TASK_FAMILY]
#   ./scripts/next-image-tag.sh cht-dev-backend us-east-1 '' cht-dev-backend
#   ./scripts/next-image-tag.sh cht-platform-backend us-east-1 v cht-platform-backend

set -euo pipefail

REPO="${1:-cht-platform-backend}"
REGION="${2:-us-east-1}"
PREFIX="${3:-}"
TASK_DEF_FAMILY="${4:-}"

if ! command -v aws >/dev/null 2>&1; then
  echo "::error::aws CLI required" >&2
  exit 1
fi

TAGS_FILE="$(mktemp)"
trap 'rm -f "$TAGS_FILE"' EXIT

if [ -n "$PREFIX" ]; then
  TAG_PATTERN="^${PREFIX}[0-9]+\\.[0-9]+\\.[0-9]+$"
else
  TAG_PATTERN='^[0-9]+\.[0-9]+\.[0-9]+$'
fi

collect_semver_tag() {
  local tag="$1"
  if [[ "$tag" =~ $TAG_PATTERN ]]; then
    echo "$tag" >> "$TAGS_FILE"
  fi
}

aws ecr describe-images \
  --repository-name "$REPO" \
  --region "$REGION" \
  --query 'imageDetails[*].imageTags[]' \
  --output text 2>/dev/null \
| tr '\t' '\n' \
| grep -E "$TAG_PATTERN" >> "$TAGS_FILE" || true

if [ -n "$TASK_DEF_FAMILY" ]; then
  DEPLOYED_IMAGE="$(aws ecs describe-task-definition \
    --task-definition "$TASK_DEF_FAMILY" \
    --region "$REGION" \
    --query 'taskDefinition.containerDefinitions[0].image' \
    --output text 2>/dev/null || true)"
  if [ -n "$DEPLOYED_IMAGE" ] && [ "$DEPLOYED_IMAGE" != "None" ]; then
    collect_semver_tag "${DEPLOYED_IMAGE##*:}"
  fi
fi

if [ ! -s "$TAGS_FILE" ]; then
  echo "${PREFIX}1.0.0"
  exit 0
fi

LATEST="$(sort -V "$TAGS_FILE" | uniq | tail -1)"
VERSION="${LATEST#"$PREFIX"}"
IFS=. read -r major minor patch <<< "$VERSION"

# Each segment is 0–9. After .9, roll the next higher segment:
#   4.1.9 → 4.2.0
#   4.9.9 → 5.0.0
patch=$((patch + 1))
if [ "$patch" -gt 9 ]; then
  patch=0
  minor=$((minor + 1))
fi
if [ "$minor" -gt 9 ]; then
  minor=0
  major=$((major + 1))
fi

echo "${PREFIX}${major}.${minor}.${patch}"
