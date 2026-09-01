#!/bin/bash
set -euo pipefail

echo "🔐 Setting up GitHub Actions OIDC for cht-companion (development / feature deploys)"
echo "===================================================================================="
echo ""

read -p "Enter GitHub username or org [OasisBureua]: " GITHUB_USER
GITHUB_USER="${GITHUB_USER:-OasisBureua}"

read -p "Enter repository name [cht-companion]: " REPO_NAME
REPO_NAME="${REPO_NAME:-cht-companion}"

read -p "Enter GitHub org ID [248812921]: " GITHUB_ORG_ID
GITHUB_ORG_ID="${GITHUB_ORG_ID:-248812921}"

read -p "Enter GitHub repo ID [1347757605]: " GITHUB_REPO_ID
GITHUB_REPO_ID="${GITHUB_REPO_ID:-1347757605}"

ROLE_NAME="GitHubActions-CHT-Companion"
POLICY_NAME="GitHubActions-CHT-Companion-Deploy"

AWS_ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo ""
echo "📋 Configuration:"
echo "  AWS Account: $AWS_ACCOUNT_ID"
echo "  GitHub repo: $GITHUB_USER/$REPO_NAME"
echo "  GitHub IDs:  org=$GITHUB_ORG_ID repo=$GITHUB_REPO_ID"
echo "  IAM role:    $ROLE_NAME"
echo ""

# New repos use immutable OIDC sub claims: repo:ORG@ORG_ID/REPO@REPO_ID:...
# Keep legacy slug-only patterns for older repos / rollback compatibility.
cat > /tmp/github-trust-policy-cht-companion.json << TRUST
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::${AWS_ACCOUNT_ID}:oidc-provider/token.actions.githubusercontent.com"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
        },
        "StringLike": {
          "token.actions.githubusercontent.com:sub": [
            "repo:${GITHUB_USER}/${REPO_NAME}:environment:development",
            "repo:${GITHUB_USER}/${REPO_NAME}:ref:refs/heads/feature/*",
            "repo:${GITHUB_USER}/${REPO_NAME}:ref:refs/heads/develop",
            "repo:${GITHUB_USER}@${GITHUB_ORG_ID}/${REPO_NAME}@${GITHUB_REPO_ID}:environment:development",
            "repo:${GITHUB_USER}@${GITHUB_ORG_ID}/${REPO_NAME}@${GITHUB_REPO_ID}:ref:refs/heads/feature/*",
            "repo:${GITHUB_USER}@${GITHUB_ORG_ID}/${REPO_NAME}@${GITHUB_REPO_ID}:ref:refs/heads/develop"
          ]
        }
      }
    }
  ]
}
TRUST

echo "🔧 Ensuring GitHub OIDC provider exists..."
aws iam create-open-id-connect-provider \
  --url https://token.actions.githubusercontent.com \
  --client-id-list sts.amazonaws.com \
  --thumbprint-list 6938fd4d98bab03faadb97b34396831e3780aea1 \
  2>/dev/null || echo "OIDC provider already exists"

echo "👤 Creating/updating IAM role $ROLE_NAME..."
ROLE_ARN="$(aws iam create-role \
  --role-name "$ROLE_NAME" \
  --assume-role-policy-document file:///tmp/github-trust-policy-cht-companion.json \
  --description "GitHub Actions deploy role for cht-companion (dev/feature branches)" \
  --query 'Role.Arn' \
  --output text 2>/dev/null || \
  aws iam get-role --role-name "$ROLE_NAME" --query 'Role.Arn' --output text)"

aws iam update-assume-role-policy \
  --role-name "$ROLE_NAME" \
  --policy-document file:///tmp/github-trust-policy-cht-companion.json

echo "✅ Role: $ROLE_ARN"

echo "📎 Attaching scoped deploy policy..."
POLICY_ARN="$(aws iam create-policy \
  --policy-name "$POLICY_NAME" \
  --policy-document "file://${SCRIPT_DIR}/iam/github-actions-deploy-policy.json" \
  --query 'Policy.Arn' \
  --output text 2>/dev/null || \
  aws iam get-policy --policy-arn "arn:aws:iam::${AWS_ACCOUNT_ID}:policy/${POLICY_NAME}" --query 'Policy.Arn' --output text)"

aws iam attach-role-policy \
  --role-name "$ROLE_NAME" \
  --policy-arn "$POLICY_ARN" 2>/dev/null || echo "Policy already attached"

echo ""
echo "✅ Development OIDC setup complete!"
echo ""
echo "GitHub OIDC sub (immutable format for this repo):"
echo "  repo:${GITHUB_USER}@${GITHUB_ORG_ID}/${REPO_NAME}@${GITHUB_REPO_ID}:environment:development"
echo ""
echo "Add this GitHub Environment secret (NOT the cht-platform-tool role):"
echo "  Environment: development"
echo "  Name:        AWS_ROLE_ARN"
echo "  Value:       $ROLE_ARN"
echo ""
echo "Used by: deploy-dev.yml, rollback.yml (development)"
echo ""

rm -f /tmp/github-trust-policy-cht-companion.json
