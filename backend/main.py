"""cht-companion RAG API entrypoint.

Layout:
  api/   — SCRUM-195 HTTP + SSE (routers, auth, schemas, sse helpers)
  db/    — SCRUM-196 pgvector schema + migrations
"""

from api import create_app

app = create_app()
