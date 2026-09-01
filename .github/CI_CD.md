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
