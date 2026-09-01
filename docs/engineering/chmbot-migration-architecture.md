# CHT Companion Migration: EC2 chmbot → cht-companion on ECS

**Status:** Accepted — **locked for implementation**  
**Owner:** Platform  
**Related (in cht-platform-tool):** [CHT-MediaHub-Go-Forward-Options.md](https://github.com/OasisBureua/cht-platform-tool/blob/main/docs/reports/CHT-MediaHub-Go-Forward-Options.md), [mediahub-platform-cutover.md](https://github.com/OasisBureua/cht-platform-tool/blob/main/docs/runbooks/mediahub-platform-cutover.md), [cognito-migration-spec.md](https://github.com/OasisBureua/cht-platform-tool/blob/main/docs/runbooks/cognito-migration-spec.md)

Migrate the MediaHub-hosted **chmbot** off shared EC2 into a CHT-owned **`cht-companion`** service on **ECS Fargate**, with **Service Connect only** (CHT backend is the sole caller), **`cht-companion-db` + pgvector**, and a path to **fully decommission MediaHub** for chat cost savings.

### Executive decisions (TL;DR)

| Topic | Decision |
| ----- | -------- |
| Product name | **CHT Companion** |
| GitHub repo | **`cht-companion`** |
| GitHub description | CHT Companion — members-only RAG chat API and knowledge-base ingest for Community Health TV (Bedrock, pgvector, Service Connect). |
| Q&A compute | **ECS Fargate** on the **existing** CHT cluster. Not Lambda for answers. Not EKS. |
| KB ingest | **Lambda `cht-companion-kb`**: code + deps in this repo (`kb/`); **separate deploy lane** from ECS |
| Networking | Service Connect only + NestJS BFF |
| DB / vectors | New **`cht-companion-db`** + **pgvector** |
| LLM | **Amazon Bedrock** (Claude) for v1 |
| Corpus | **CHT catalog clip metadata + YouTube captions** as primary; curated docs later |
| S3 | **Skip at launch**; add raw-archive bucket only if reprocess/audit needs it |
| UI | **First-party React chat** on `/app/chatbot` in **cht-platform-tool** (no iframe; no frontend in this repo) |
| Bubble | **Members-only** (same authenticated API); drop anonymous public chat |
| Code home | **This repo:** FastAPI Q&A + KB Lambda source. **cht-platform-tool:** BFF + React UI |
| API shape | **SSE** `POST /chat`: `{ "query" }` → streamed `data: {"text": "..."}` events, then `data: [DONE]` |
| RDS size (start) | **`db.t4g.small`**, single-AZ **dev** / Multi-AZ **prod** when traffic justifies |
| Environments | **`dev`** and **`prod` only** — no staging. **dev** = NestJS **`development`** (devapp, `cht-dev-*`, GitHub env **`development`**) |
| Related names | Lambda **`cht-companion-kb`**; optional later S3 **`cht-companion-raw`** |

---

## 1. Why migrate

Today the chatbot runs on the same MediaHub EC2 as the monolith. That creates:

| Risk | Impact |
| ---- | ------ |
| Single host SPOF | Chatbot outage if EC2 / Compose fails |
| Cost & coupling | Paying for MediaHub host capacity for a CHT-only UX |
| Auth coupling | GoTrue JWT via iframe; Cognito cutover breaks authenticated chat |
| No independent scale | RAG competes with Hub workloads on one box |

**Goal:** First-party CHT Companion (`cht-companion`), private to the platform VPC, independent DB and deploys, no MediaHub runtime dependency.

---

## 2. Current architecture

```text
┌─────────────────────────────────────────────────────────────────┐
│ CHT Platform (cht-platform-tool)                                 │
│  Browser → CloudFront → S3 (React)                               │
│    /app/chatbot  → ChatBot.tsx iframe                            │
│    ChatBubble    → floating iframe (anonymous only today)        │
│  NestJS GET /api/auth/chatbot-token → session accessToken        │
└────────────────────────────┬────────────────────────────────────┘
                             │ iframe + ?token=<JWT>
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│ MediaHub EC2                                                     │
│  https://chmbot.communityhealth.media/widget                     │
│  chmbot process + Hub monolith + Docker Postgres/Redis + KB      │
└─────────────────────────────────────────────────────────────────┘
```

| Surface | Detail |
| ------- | ------ |
| Full page | `frontend/src/pages/ChatBot.tsx` → hardcoded widget URL |
| Bubble | `frontend/src/components/ChatBubble.tsx` → same URL, no token |
| Token | `GET /api/auth/chatbot-token` |

There is **no** chatbot Terraform/ECR in cht-platform-tool today. Target: own Q&A + ingest under CHT (`cht-companion` + `cht-companion-db` + `cht-companion-kb`).

---

## 3. Compute: ECS vs Lambda vs EKS (locked)

**Do not stand up a new ECS cluster or EKS for chat.** Reuse the existing CHT cluster. Split **request path** vs **ingest path**:

| Workload | Decision | Why |
| -------- | -------- | --- |
| **Interactive RAG / chat API** (`cht-companion`) | **ECS Fargate** on the **existing** CHT cluster + Service Connect | Sync POST still waits on multi-second Bedrock + retrieval; warm process and pooled RDS; native Service Connect (`cht-companion:8080`); same ECR → ECS path as the platform backend |
| **KB ingest / re-embed** (`cht-companion-kb`) | **Lambda** + EventBridge + SQS | Bursty, schedulable, scale-to-zero; cheapest for caption fetch + embed jobs |
| **Q&A on Lambda** | **No for v1** | SSE + multi-second Bedrock is a poor Lambda fit; no Service Connect; VPC+pgvector cold starts. Ingest Lambda in `kb/` does **not** mean answers run on Lambda |
| **EKS** | **No** | CHT has no Kubernetes today. New control plane/nodes/add-ons for one small API is the “new cluster” cost already rejected |

```text
Locked hybrid:

  NestJS (existing ECS)  --Service Connect-->  cht-companion (Fargate, same cluster)
                                                      |
                                                      v
                                                 cht-companion-db (pgvector)

  EventBridge schedule / SQS  -->  cht-companion-kb (Lambda, code in this repo)  -->  cht-companion-db
```

### Why not Lambda-only for chat answers?

- Member chat often needs **>30s** retrieval + generation; a warm Fargate task with a pooled RDS connection is simpler than VPC Lambda ENI/cold-start on every question.
- You already run NestJS on Fargate; one more small service is incremental, not a new platform.
- SSE is the member UX (tokens as they generate). NestJS BFF **proxies the stream**; Fargate stays warm for Bedrock + pgvector. That is why Q&A is not Lambda.

### Cost note

| Pattern | Idle cost | Fit |
| ------- | --------- | --- |
| Fargate `cht-companion` desired 1–2 | Small always-on | Answers |
| Lambda KB | ~$0 idle | Ingest |
| Always-on ECS KB worker | Wastes money | Avoid |
| Separate ECS cluster or EKS | Extra fixed cost | Avoid |

**Chosen:** hybrid — **Fargate `cht-companion` on existing cluster** + **Lambda for KB**. Not Lambda-only for Q&A; not EKS; not a dedicated chat cluster.

---

## 4. Target architecture (locked)

| Decision | Choice |
| -------- | ------ |
| Service | **`cht-companion`** (replaces chmbot) — Python FastAPI on Fargate |
| Database | **`cht-companion-db`** — dedicated Postgres + **pgvector** |
| Exposure | **ECS Service Connect only** — only CHT NestJS calls it |
| MediaHub | **Decommission for chat** — no Hub EC2/RDS dependency for RAG |
| UI | **React** `/app/chatbot` → SSE `POST /api/chat` in cht-platform-tool (no iframe) |
| Access | **Members-only** (no anonymous LLM) |
| LLM | **Bedrock** |
| Corpus | CHT catalog IDs + YouTube captions |
| S3 | Skip at launch |

```text
 Browser (CHT React)
        │  same-origin POST /api/chat  (session / Cognito, SSE)
        ▼
 ┌──────────────────────┐
 │ CHT NestJS (ECS)     │  BFF: auth, rate limits, SSE proxy
 │ cht-platform-backend │
 └──────────┬───────────┘
            │  Service Connect → POST http://cht-companion:8080/chat (SSE)
            ▼
 ┌──────────────────────┐         ┌─────────────────────┐
 │ cht-companion (Fargate)   │────────▶│ cht-companion-db (RDS)   │
 │ FastAPI, same CHT cluster │         │ Postgres + pgvector │
 └──────────────────────┘         └──────────▲──────────┘
                                             │
 ┌──────────────────────┐                    │
 │ cht-companion-kb (Lambda) │────────────────────┘
 │ code in this repo kb/ │
 │ EventBridge / SQS     │
 └──────────────────────┘
            │
            ▼
      Bedrock / LLM APIs (NAT egress)
```

### Service decomposition

| Service | Role | Notes |
| ------- | ---- | ----- |
| **cht-companion** | RAG API | Fargate on **existing** CHT cluster + Service Connect; **no public ALB**; **no new cluster**; **no EKS** |
| **cht-companion-kb** | Chunk + embed jobs | **Lambda** + EventBridge/SQS → `cht-companion-db`; **source in `kb/`**; deploy on the **kb lane** (not with ECS) |
| **cht-companion-db** | Vector + chunk SoR | Small RDS; not CHT Aurora |
| **CHT BFF** | `POST /api/chat` (SSE) | Existing NestJS in cht-platform-tool; sole ingress |
| **S3** | Skip v1 | Add later only for raw archives |
| **Secrets / CW** | Keys, logs, alarms | Same platform patterns |

---

## 5. Auth model

### Today

Iframe + GoTrue/Cognito token query param; anonymous bubble rate-limited on chmbot.

### Target (BFF + Service Connect)

| Mode | Auth | Enforced at |
| ---- | ---- | ----------- |
| Logged-in member | CHT session / Cognito | NestJS `POST /api/chat` (SSE proxy) |
| Guest | Sign-in CTA; **no LLM** | NestJS / React |
| `cht-companion` | Private VPC + SG + Service Connect + **internal shared secret** (Secrets Manager) | No public JWT on chat service |

Retire `/api/auth/chatbot-token` and `chmbot.*` after cutover.

---

## 6. Knowledge base & do you still need S3?

```text
Sources (YouTube / CHT catalog / curated docs — not MediaHub long-term)
        │
        ▼
 cht-companion-kb → chunk + embed
        │
        ▼
 cht-companion-db (pgvector)  ← system of record for retrieval
        │
        ▼
 cht-companion → retrieve → LLM → answer
```

### S3 answer

**No — S3 is not required as the KB** when using pgvector.

| | Role |
| - | ---- |
| **`cht-companion-db`** | Chunk text + embeddings + citation metadata (**RAG index**) |
| **S3** | **Optional** cheap archive of raw VTT/JSON/PDFs for reprocess/audit |

| Approach | When |
| -------- | ---- |
| **Skip S3 (fine to start)** | Corpus fits in RDS; re-fetch from YouTube/API on full rebuild |
| **Add small S3 later** | Large raw files, drop-zone ingest, cheaper cold storage than Postgres |
| **Avoid** | Using S3 itself as the similarity-search store |

---

## 7. Networking & security

| Control | Target |
| ------- | ------ |
| Ingress to `cht-companion` | Service Connect from NestJS only |
| Public chat ALB / `chmbot.*` | None after cutover |
| DB | Private; SG from `cht-companion` + `cht-companion-kb` only |
| LLM egress | NAT |
| Secrets | Secrets Manager (including BFF↔companion internal secret); no keys on EC2 |

---

## 8. Repo, API, and CI/CD (locked)

### Repo layout (`cht-companion` — same top-level shape as cht-platform-tool, **no frontend**)

```text
cht-companion/
├── backend/            # FastAPI RAG API → ECR cht-companion / cht-dev-companion, port 8080
├── kb/             # cht-companion-kb Lambda source + dependencies
├── infrastructure/     # Terraform (later): ECS, Service Connect, cht-companion-db, SG, secrets, Lambda/EventBridge/SQS
├── .github/workflows/  # Mirror cht-platform-tool; independent backend vs kb vs infra lanes
├── scripts/
└── docs/
```

BFF (`POST /api/chat` SSE) and React `/app/chatbot` + bubble stay in **cht-platform-tool**.

### API contract (SSE)

**Backend** (private, Service Connect):

| Method | Path | Body | Response |
| ------ | ---- | ---- | -------- |
| GET | `/health`, `/health/ready`, `/health/live` | — | health JSON |
| POST | `/chat` | `{ "query": "..." }` | `text/event-stream`: `data: {"text": "..."}` chunks, then `data: [DONE]` |

No public JWT. NestJS BFF streams the same events to the browser.

**BFF** (cht-platform-tool): `POST /api/chat` — session/Cognito, rate limits, **SSE proxy** to `http://cht-companion:8080/chat`.

### Deploy lanes (same repo, independent)

| Lane | Paths | What runs |
| ---- | ----- | --------- |
| Backend | `backend/**` | Image + ECS image roll |
| KB | `kb/**` | Lambda deploy (image or zip). **Does not** roll ECS |
| Infra | `infrastructure/**` | Terraform plan/apply (once that tree exists) |

A `backend/**` change must not deploy Lambda. A `kb/**` change must not roll ECS. Same idea as cht-platform-tool backend vs frontend lanes.

### CI/CD (mirror cht-platform-tool)

| Item | Decision |
| ---- | -------- |
| Workflows | `pr-validation`, `branch-policy`, `security-monthly`, `deploy-dev`, `deploy-prod`, `rollback` |
| Auth | GitHub OIDC → same AWS account/region (`us-east-1`) |
| Dev ECR / ECS | `cht-dev-companion` on `cht-dev-cluster`; Lambda `cht-dev-companion-kb` |
| Prod ECR / ECS | `cht-companion` on existing `cht-platform-cluster`; Lambda `cht-companion-kb` |
| Image tags | Dev `1.0.x` + `dev-latest`; prod `v1.0.x` + `prod-latest` |
| GitHub environments | **`development`** (dev), **`prod`** — same naming as cht-platform-tool NestJS deploys |
| Prod trigger | Manual `workflow_dispatch` |
| Branch policy | PRs to `main` from `release/*` or `hotfix/*` |

**Environment naming (no staging)**

| Shorthand | NestJS / cht-platform-tool | GitHub Actions env | Typical targets |
| --------- | -------------------------- | ------------------ | --------------- |
| **dev** | **`development`** | `development` | devapp, `cht-dev-cluster`, `cht-dev-companion` |
| **prod** | **production** | `prod` | testapp / prod app, `cht-platform-cluster`, `cht-companion` |

---

## 9. Migration plan

### Phase 0 — Lock design + scaffold `cht-companion`

- [x] Architecture accepted (this document)
- [ ] Inventory current chmbot prompts and corpus sources
- [x] Scaffold `backend/` FastAPI: health + SSE `POST /chat` stub; Dockerfile
- [x] Scaffold `kb/` Lambda stub + dependencies in this repo
- [x] CI/CD mirroring cht-platform-tool with **separate backend and kb deploy lanes** (no frontend lane)
- [ ] Confirm corpus after MediaHub decommission (YouTube / CHT catalog)

### Phase 1 — Dev compute + data plane

- [ ] Provision **`cht-companion-db`** (Postgres + `vector`), single-AZ `db.t4g.small`
- [ ] ECS `cht-companion` on existing `cht-dev-cluster`; Service Connect `cht-companion:8080`; SG; Secrets Manager; Bedrock task role
- [ ] No public ALB. No EKS. No Lambda for Q&A

### Phase 2 — KB ingest (same repo, kb deploy lane)

- [ ] Implement `kb/` (`cht-companion-kb`): EventBridge schedule for periodic caption refresh; SQS for on-demand re-embed
- [ ] Deploy Lambda **without** rolling ECS unless `backend/` also changed
- [ ] Seed pgvector from catalog IDs + YouTube captions (optional one-time snapshot from old chmbot as bootstrap only)
- [ ] Skip S3 at launch

### Phase 3 — CHT BFF + UI (`cht-platform-tool`)

- [ ] NestJS `POST /api/chat`: Cognito/session auth, rate limit, **SSE proxy** to Service Connect
- [ ] Replace iframe: React `/app/chatbot` + bubble, members-only (sign-in CTA for guests)
- [ ] Retire `GET /api/auth/chatbot-token` after cutover

### Phase 4 — Dev quality gate

- [ ] BFF → companion → Bedrock + pgvector spot-checks in **dev** vs a fixed prompt set
- [ ] Alarms: ECS health, RDS, Bedrock spend budget

### Phase 5 — Prod cutover + decommission

- [ ] Deploy prod `cht-companion` / `cht-companion-db` / `cht-companion-kb` / BFF routes / UI
- [ ] Switch `/app/chatbot` + bubble to CHT APIs (no dual iframe provider)
- [ ] Stop EC2 chmbot; 48h soak
- [ ] Remove `chmbot.*` / MediaHub chat dependency; delete chatbot-token path if unused
- [ ] Update architecture diagrams and IR docs

**Ownership**

```text
cht-companion     → backend/ (ECS FastAPI) + kb/ (Lambda code+deps)
                    independent CI lanes; Terraform for ECS + DB + Lambda
cht-platform-tool → POST /api/chat SSE BFF + React chat UI
```

---

## 10. Cutover checklist

**Pre:** dev BFF→Service Connect SSE `POST /chat` works; RAG spot-checks; rollback plan (iframe only while EC2 chmbot still runs).

**Go:** enable `POST /api/chat` in prod; disable iframe.

**Post:** EC2 chatbot stopped; no MediaHub calls on chat path; alarms green 48h.

---

## 11. Rollback

1. Feature-flag frontend back to iframe **only while EC2 chmbot still runs**.
2. Or serve static “chat unavailable” if Hub already gone.
3. Keep `cht-companion` tasks up for fast re-enable.
4. No `legacy_iframe` dual provider in v1 — rollback is emergency-only.

---

## 12. Success criteria

- [ ] Production chat via **`cht-companion`** on Fargate + Service Connect
- [ ] **`cht-companion-db` + pgvector** is the RAG store
- [ ] **`cht-companion-kb`** code lives in this repo and deploys on its own lane
- [ ] No public chatbot URL required for CHT members
- [ ] No MediaHub EC2 dependency for chat
- [ ] CHT session/Cognito enforced at NestJS BFF
- [ ] SSE `POST /chat` (query in, streamed answer out)

---

## 13. Cost sketch

| Component | Notes |
| --------- | ----- |
| Fargate `cht-companion` | Modest always-on |
| Lambda `cht-companion-kb` | ~$0 idle |
| **`cht-companion-db` small RDS** | Primary new fixed cost (still ≪ OpenSearch Serverless) |
| No chat ALB | Saves vs public widget ALB |
| S3 | $0 if skipped; pennies–low if raw archive only |
| LLM tokens | Usage-driven; set budgets |

Decommissioning MediaHub EC2 (for chat and eventually Hub) is the large savings lever.

---

## 14. Service Connect (confirmed)

Because **only CHT** will call chat:

1. No public ALB for `cht-companion`.
2. Service Connect name: `cht-companion:8080`.
3. NestJS BFF **SSE-proxies** `POST /api/chat` → `POST http://cht-companion:8080/chat`.
4. React talks to CHT only (same origin).

Browsers never resolve Service Connect names — the BFF is mandatory for this model.

---

## 15. Vector store & database (confirmed)

| Topic | Decision |
| ----- | -------- |
| Engine | **pgvector** (not OpenSearch for v1) |
| Database | **New `cht-companion-db`** |
| Not on | CHT Aurora, Content Hub DB, MediaHub RDS |

OpenSearch only if hybrid search/scale later demands it.

---

## 16. Decision log (locked)

Treat as the default build plan unless product explicitly overrides.

### 16.1 LLM → **Amazon Bedrock (Claude)**

| Option | Verdict |
| ------ | ------- |
| **Bedrock (locked)** | IAM auth via task role (no long-lived API keys in Secrets for the model), AWS BAA path, CloudWatch-friendly, fits private VPC egress story |
| Direct OpenAI/Anthropic API | Fine as fallback; more key rotation / vendor surface |

**v1:** one chat model (Claude Sonnet-class) + one embedding model on Bedrock (Titan embeddings). Abstract behind an interface so the provider can change later. Concrete model IDs live in env / task definition. Set **monthly budget alarms** on Bedrock spend day one.

### 16.2 Corpus after MediaHub → **CHT catalog + YouTube captions**

Do **not** keep a long-term MediaHub dependency for KB ingest.

| Source | Role |
| ------ | ---- |
| **Primary** | Clip/show IDs and titles already known to CHT (catalog / podcasts) → fetch **YouTube captions/transcripts** in `cht-companion-kb` |
| **Secondary (phase 2+)** | Curated admin uploads (FAQ, program disclaimers, policy snippets) into `cht-companion-db` |
| **Avoid as SoR** | Scraping MediaHub admin DB or relying on Hub EC2 for transcripts |

Export a one-time snapshot from current chmbot/Hub KB only as a **bootstrap** seed, then own refresh in CHT.

### 16.3 S3 → **skip at launch**

pgvector in `cht-companion-db` is enough for RAG. Re-fetch captions from YouTube on full rebuild. **Add** `cht-companion-raw` S3 later only if you need durable raw VTT/PDF archives or an admin drop-zone.

### 16.4 Chat UI → **first-party React**; API → **SSE**

Rebuild `/app/chatbot` (and bubble) as CHT React calling **`POST /api/chat`** and consuming the event stream. Do not keep an iframe widget.

**BFF API:** NestJS **SSE proxy** to FastAPI `POST /chat`. Events: `data: {"text": "..."}` then `data: [DONE]`.

### 16.5 Anonymous bubble → **members-only**

Require login for chat (full page + bubble). Anonymous public LLM access adds abuse/cost risk with little product value once chat is CHT-owned. Guests see a sign-in CTA.

### 16.6 Code, deploy, and sizing defaults

| Item | Decision |
| ---- | -------- |
| Q&A repo tree | **`backend/`** FastAPI on Fargate (same top-level name as cht-platform-tool) |
| KB repo tree | **`kb/`** in this repo (code + deps); **separate CI deploy lane** |
| Frontend | **cht-platform-tool only** |
| `cht-companion` tasks | Start **desired 1** dev / **2** prod; 0.5–1 vCPU |
| `cht-companion-kb` | **Lambda** (+ EventBridge/SQS); never always-on Fargate |
| `cht-companion-db` | Start **`db.t4g.small`**, gp3; enable `vector`; Multi-AZ when chat is prod-critical |
| Feature flag | **Not required** — ship new path; no `legacy_iframe` dual provider |

### 16.7 Build sequence

1. Scaffold `backend/` + `kb/` + CI (independent lanes; no Terraform apply)
2. Terraform in this repo: `cht-companion-db` + ECS `cht-companion` + Service Connect + SG + secrets
3. `kb/`: YouTube caption ingest → embeddings → pgvector (deploy on kb lane)
4. NestJS SSE `POST /api/chat` BFF + React chat UI in cht-platform-tool
5. Dev quality gate in **dev** (fixed prompt set vs old chmbot)
6. Prod cutover → stop EC2 chmbot → retire token/iframe code

---

## 17. Related documents

These live in **cht-platform-tool** unless noted.

| Doc | Relevance |
| --- | --------- |
| cht-platform-tool `docs/engineering/platform-cost-reduction.md` | EC2 off, dev lightswitch, right-sizing |
| cht-platform-tool `docs/reports/CHT-MediaHub-Go-Forward-Options.md` | Broader Hub recovery / decommission context |
| cht-platform-tool `docs/runbooks/mediahub-platform-cutover.md` | Hub ECS cutover (chat can precede full Hub retirement) |
| cht-platform-tool `docs/runbooks/cognito-migration-spec.md` | Legacy chatbot JWT gap — moot once BFF owns auth |
| cht-platform-tool `docs/engineering/architecture.md` | CHT platform overview |
| cht-platform-tool `docs/FRS-functional-requirements-specification.md` (FRS-APP-013) | Chatbot functional requirement |
