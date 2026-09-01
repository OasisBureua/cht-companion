#!/usr/bin/env bash
# Dev semver tag helper for cht-companion ECR.
exec "$(dirname "$0")/next-image-tag.sh" \
  "${1:-cht-dev-companion}" \
  "${2:-us-east-1}" \
  "" \
  "cht-dev-companion"
