#!/usr/bin/env bash
# Set deploy_backend / deploy_kb / deploy_infra for GitHub Actions.
#
# Lanes are independent:
#   - backend → backend/** (ECS FastAPI image roll)
#   - kb      → kb/**      (Lambda cht-companion-kb)
#   - infra   → infrastructure/**
#
# Usage: ci-detect-deploy-scope.sh <force_all> <backend_changed> <kb_changed> <infra_changed>
set -euo pipefail

FORCE_ALL="${1:-false}"
BACKEND_CHANGED="${2:-false}"
KB_CHANGED="${3:-false}"
INFRA_CHANGED="${4:-false}"

DEPLOY_BACKEND=false
DEPLOY_KB=false
DEPLOY_INFRA=false

if [ "$FORCE_ALL" = "true" ]; then
  DEPLOY_BACKEND=true
  DEPLOY_KB=true
  DEPLOY_INFRA=true
else
  if [ "$BACKEND_CHANGED" = "true" ]; then
    DEPLOY_BACKEND=true
  fi
  if [ "$KB_CHANGED" = "true" ]; then
    DEPLOY_KB=true
  fi
  if [ "$INFRA_CHANGED" = "true" ]; then
    DEPLOY_INFRA=true
  fi
fi

{
  echo "deploy_backend=$DEPLOY_BACKEND"
  echo "deploy_kb=$DEPLOY_KB"
  echo "deploy_infra=$DEPLOY_INFRA"
} >> "${GITHUB_OUTPUT:?GITHUB_OUTPUT not set}"

echo "Deploy scope: backend=$DEPLOY_BACKEND kb=$DEPLOY_KB infra=$DEPLOY_INFRA (force_all=$FORCE_ALL)"
