#!/bin/bash
set -euo pipefail

POLICY_NAME="GitHubActions-CHT-Companion-Deploy"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AWS_ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
POLICY_ARN="arn:aws:iam::${AWS_ACCOUNT_ID}:policy/${POLICY_NAME}"

echo "Updating IAM policy ${POLICY_NAME}..."

# A managed policy keeps at most 5 versions. Drop the oldest non-default
# version so create-policy-version can succeed on the next update.
VERSION_COUNT="$(aws iam list-policy-versions --policy-arn "$POLICY_ARN" --query 'length(Versions)' --output text)"
if [ "$VERSION_COUNT" -ge 5 ]; then
  OLDEST="$(aws iam list-policy-versions --policy-arn "$POLICY_ARN" \
    --query 'sort_by(Versions[?IsDefaultVersion==`false`], &CreateDate)[0].VersionId' --output text)"
  echo "Deleting oldest non-default version ${OLDEST}..."
  aws iam delete-policy-version --policy-arn "$POLICY_ARN" --version-id "$OLDEST"
fi

aws iam create-policy-version \
  --policy-arn "$POLICY_ARN" \
  --policy-document "file://${SCRIPT_DIR}/iam/github-actions-deploy-policy.json" \
  --set-as-default

echo "✅ Policy updated. Re-run deploy-dev (infra lane) or terraform apply."
