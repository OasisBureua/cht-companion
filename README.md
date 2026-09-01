# CHT Companion

Members-only RAG chat API and knowledge-base ingest for Community Health TV (Bedrock, pgvector, Service Connect).

Chat UI and NestJS BFF (`POST /api/chat` SSE proxy) live in **cht-platform-tool**, not this repo.

## Layout

Same top-level shape as cht-platform-tool, without a frontend:

```
cht-companion/
├── backend/            # FastAPI RAG API (ECS Fargate, port 8080, SSE POST /chat)
├── kb/                 # cht-companion-kb Lambda (chunk + embed)
├── infrastructure/     # Terraform later (ECS, RDS, Service Connect, Lambda)
├── .github/workflows/  # Mirror cht-platform-tool; independent backend vs kb lanes
├── scripts/
└── docs/
```

## Local

```bash
# API
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8080

# Tests
pytest
cd ../kb && pip install -r requirements.txt && pytest
```

`POST /chat` with `{ "query": "..." }` returns an SSE stream (`data: {"text": "..."}` then `data: [DONE]`).

See [docs/engineering/chmbot-migration-architecture.md](docs/engineering/chmbot-migration-architecture.md) and [.github/CI_CD.md](.github/CI_CD.md).
