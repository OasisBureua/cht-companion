#!/bin/bash
set -euo pipefail

POLICY_NAME="GitHubActions-CHT-Companion-Deploy"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AWS_ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
POLICY_ARN="arn:aws:iam::${AWS_ACCOUNT_ID}:policy/${POLICY_NAME}"

echo "Updating IAM policy ${POLICY_NAME}..."

aws iam create-policy-version \
  --policy-arn "$POLICY_ARN" \
  --policy-document "file://${SCRIPT_DIR}/iam/github-actions-deploy-policy.json" \
  --set-as-default

echo "✅ Policy updated. Re-run deploy-dev (infra lane) or terraform apply."
