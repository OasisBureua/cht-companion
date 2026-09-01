#!/usr/bin/env bash
# Prod semver tag helper for cht-companion ECR.
exec "$(dirname "$0")/next-image-tag.sh" \
  "${1:-cht-companion}" \
  "${2:-us-east-1}" \
  "v" \
  "cht-companion"
