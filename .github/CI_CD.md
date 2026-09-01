# CI/CD

## Workflows

| Workflow | Trigger | Purpose |
|----------|---------|---------|
| `pr-validation.yml` | Pull requests | Backend + kb tests |
| `branch-policy.yml` | PRs → `main` | Require head branch `release/*` or `hotfix/*` |
| `security-monthly.yml` | First Monday monthly | pip audit, Trivy filesystem scan |
| `deploy-dev.yml` | Push to `feature/**` (app paths), manual | Images (`1.0.0`, …) → `cht-dev-*` ECR; independent backend vs kb lanes |
| `deploy-prod.yml` | Manual | Prod deploy → `cht-companion` / `cht-companion-kb` |
| `rollback.yml` | Manual | Roll back ECS `cht-companion` |

Docs-only changes under `docs/**` do not trigger dev deploy. There is **no frontend lane** (UI lives in cht-platform-tool).

## Deploy scope

| Lane | Paths | What runs |
|------|--------|-----------|
| Backend | `backend/**` | FastAPI image + ECS roll |
| KB | `kb/**` | Lambda `cht-companion-kb` image |
| Infra | `infrastructure/**` | Terraform plan/apply once that tree exists |

A backend change does not deploy the Lambda. A kb change does not roll ECS.

Change base matches cht-platform-tool: push `before` SHA, last successful run, merge-base with `develop` (dev) or `main` (prod).

**GitHub environments:** **`development`** (dev; NestJS BFF on devapp) and **`prod`** only — no staging.

## GitHub environments (required)

Create two environments under **Settings → Environments**:

| Environment | Workflows | Secrets (now) | Secrets (when Terraform apply is wired) |
|-------------|-----------|---------------|----------------------------------------|
| **`development`** | `deploy-dev.yml`, `rollback.yml` (dev) | `AWS_ROLE_ARN` | `TF_VAR_internal_api_secret` |
| **`prod`** | `deploy-prod.yml`, `rollback.yml` (prod) | `AWS_ROLE_ARN` | `TF_VAR_internal_api_secret` |

### One-time AWS setup

From a machine with AWS admin (or IAM role create) access:

```bash
./infrastructure/aws-github-oidc-setup.sh      # → paste role ARN into development
./infrastructure/aws-github-oidc-setup-prod.sh  # → paste role ARN into prod
```

- **Development role** (`GitHubActions-CHT-Companion`): trusts any workflow run from `OasisBureua/cht-companion` (feature branches, manual dev deploy).
- **Production role** (`GitHubActions-CHT-Companion-Prod`): trusts only runs that use GitHub environment **`prod`** (matches `deploy-prod.yml`).

**New repos:** GitHub OIDC `sub` claims include immutable org/repo IDs (e.g. `repo:OasisBureua@248812921/cht-companion@1347757605:environment:development`). The setup scripts trust both slug-only and immutable formats. If AssumeRole still fails, check CloudTrail `userName` on `AssumeRoleWithWebIdentity` events and re-run the setup script.

Use **different** `AWS_ROLE_ARN` values on each environment. Do not reuse cht-platform-tool’s role unless you extend its trust policy to include this repo.

See [infrastructure/README.md](../infrastructure/README.md) for details.
