# CHT Companion infrastructure

Terraform for ECS `cht-companion`, Service Connect, `cht-companion-db` (pgvector), SG, secrets, and Lambda `cht-companion-kb` + EventBridge/SQS.

See [docs/engineering/chmbot-migration-architecture.md](../docs/engineering/chmbot-migration-architecture.md).

## GitHub Actions OIDC (one-time)

Workflows use **OIDC** (`AWS_ROLE_ARN`), not long-lived access keys. Run these once per AWS account with credentials that can create IAM roles:

```bash
# Development / feature-branch deploys (deploy-dev.yml)
./infrastructure/aws-github-oidc-setup.sh

# Production deploys (deploy-prod.yml) — trusts GitHub environment "prod" only
./infrastructure/aws-github-oidc-setup-prod.sh
```

Defaults: org `CommunityHealthMedia`, repo `cht-companion`. Creates:

| Script | IAM role | GitHub environment secret |
|--------|----------|---------------------------|
| `aws-github-oidc-setup.sh` | `GitHubActions-CHT-Companion` | `development` → `AWS_ROLE_ARN` |
| `aws-github-oidc-setup-prod.sh` | `GitHubActions-CHT-Companion-Prod` | `prod` → `AWS_ROLE_ARN` |

Both attach [iam/github-actions-deploy-policy.json](./iam/github-actions-deploy-policy.json) (ECR push/pull for companion repos). Extend that policy when Terraform apply adds ECS, Lambda, and state bucket permissions.

**GitHub:** Settings → Environments → create **`development`** and **`prod`** → add `AWS_ROLE_ARN` on each (different role ARNs).

## Terraform (not applied yet)

```bash
cd infrastructure/terraform/environments/us-east-1

# Dev state
terraform init -backend-config=../backends/us-east-1-development.hcl
terraform plan -var-file=../variables/development.github.tfvars

# Prod state
terraform init -backend-config=../backends/us-east-1-prod.hcl
terraform plan -var-file=../variables/prod.github.tfvars
```

State bucket `cht-companion-terraform-state` must exist before `terraform init`. Do not `apply` until ready to pave.
