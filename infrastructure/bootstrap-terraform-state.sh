#!/bin/bash
set -euo pipefail

BUCKET="cht-companion-terraform-state"
REGION="us-east-1"

echo "Creating Terraform state bucket s3://${BUCKET} (${REGION})..."

if aws s3api head-bucket --bucket "$BUCKET" 2>/dev/null; then
  echo "Bucket already exists."
else
  aws s3api create-bucket \
    --bucket "$BUCKET" \
    --region "$REGION"
fi

aws s3api put-bucket-versioning \
  --bucket "$BUCKET" \
  --versioning-configuration Status=Enabled

aws s3api put-bucket-encryption \
  --bucket "$BUCKET" \
  --server-side-encryption-configuration '{
    "Rules": [{
      "ApplyServerSideEncryptionByDefault": { "SSEAlgorithm": "AES256" },
      "BucketKeyEnabled": true
    }]
  }'

aws s3api put-public-access-block \
  --bucket "$BUCKET" \
  --public-access-block-configuration \
    BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true

echo "✅ State bucket ready: s3://${BUCKET}"
