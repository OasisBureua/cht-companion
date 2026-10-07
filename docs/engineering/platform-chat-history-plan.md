# cht-platform-tool: what to do for Companion


Everything cht-platform-tool needs so the current cht-companion changes work end to end. Sections are in priority order.

| # | Item | Why | Size |
| --- | --- | --- | --- |
| 1 | [Keep the public catalog API stable](#1-keep-the-public-catalog-api-stable) | The KB now embeds every catalog clip from it | Small (mostly "don't break") |
| 2 | [Citation chips](#2-citation-chips) | One chip per source, below the answer, internal links for clip pages | Small |
| 3 | [Chat history](#3-chat-history) | Follow-up questions only work with real history | Medium |
| 4 | [Rotate the companion secret](#4-rotate-companion_internal_secret) | The live value was pasted in chat | Small, ops only |
| 5 | [Cognito M2M for platform → companion](#5-planned-cognito-m2m-for-platform--companion) | Replace the shared secret with scoped tokens | Planned, on hold |

## Where things stand (cht-companion, not deployed yet)

- `POST /chat` uses `history` to rewrite follow-up questions into standalone searches and passes the history into the answer. `conversation_id` is accepted but not stored; the platform owns history.
- Retrieval is hybrid (vector + Postgres full text) with a distance cutoff and Cohere reranking.
- One `citation` event per **source**, not per chunk.
- Knowledge base sources and their citation links:

| `source_type` | What it is | Citation `url` |
| --- | --- | --- |
| `catalog_clip` | Every catalog clip, embedded from its ContentHub `ai_summary` + `description` (~490 on dev, ~474 on prod) | `https://{devapp,app}.communityhealth.media/catalog/clip/<youtube_id>` |
| `curated_doc` | Files dropped in the S3 raw bucket: site pages (`about`, `contact`, `privacy`, `terms`), PDFs, the 24 podcast transcripts | Site page URL from front matter, or the podcast's YouTube URL |
| `youtube_caption` | Older bootstrap transcripts | YouTube URL, sometimes with `?t=` |

## 1. Keep the public catalog API stable

The KB enqueue Lambda reads `GET /api/catalog/clips` every day (dev: `devapp.communityhealth.media`, prod: `app.communityhealth.media`). ContentHub is only reachable through the platform, so this endpoint is now a dependency of the chatbot.

Keep, without auth:

- Query params `limit`, `offset`, `sort_by=recent`. The Lambda pages with `limit=50`.
- Item fields: `id` (`official:youtube:<11-char id>`), `title`, `ai_summary`, `description`, `doctors`, `tags`, `is_short`, `posted_at`, `youtube_url`.
- The clip page route `/catalog/clip/:id` accepting the 11-character YouTube id (what `getShortClipId` produces). Citations link there.

Worth fixing (the Lambda already works around both):

- `total` is wrong: it reports 75 on prod and 92 on dev while paging returns ~475 and ~492. It looks like the size of the last page. Return the real count from ContentHub.
- The same clip can appear on two consecutive pages (seen on both envs). `sort_by=recent` likely has ties on `posted_at`; add a stable tiebreaker such as `id`.

If the endpoint ever needs auth or moves, tell cht-companion first: the Lambda reads it from `CHT_PLATFORM_CATALOG_URL` (Terraform `kb_platform_catalog_url`).

## 2. Citation chips

In `frontend/src/pages/CompanionChat.tsx`:

- Move the chips **below** the answer text (they render above it today, at `mb-2`).
- Dedupe chips by `source_id`, not `citation_id`. Keep the full citation list in message state so inline `[cN]` markers in `renderAssistantText` still resolve, including older answers that had several citations for one source.
- Internal links: `catalog_clip` URLs (and site pages) point at the platform itself. When `new URL(c.url).origin === window.location.origin`, navigate with React Router (`<Link to={pathname}>`) instead of opening a new tab. Keep `target="_blank"` for YouTube and other external URLs. Apply the same rule to the inline `[cN]` links.
- Optional: label chips by type, e.g. a video icon for `catalog_clip` / `youtube_caption` and a page icon for `curated_doc`.

`CitationEvent.source_type` in `frontend/src/api/companionChat.ts` is already `string`, so no type change is needed.

## 3. Chat history

The platform today builds `history` from React state (lost on refresh, and the client can send anything) and always sends `conversation_id: null`.

### 3.1 Database (Prisma)

Add to `backend/prisma/schema.prisma`:

```prisma
// on model User, in Relations
companionConversations CompanionConversation[]

model CompanionConversation {
  id        String   @id @default(cuid())
  userId    String
  title     String
  createdAt DateTime @default(now())
  updatedAt DateTime @updatedAt

  user     User               @relation(fields: [userId], references: [id], onDelete: Cascade)
  messages CompanionMessage[]

  @@index([userId, updatedAt])
  @@map("CompanionConversation")
}

model CompanionMessage {
  id             String   @id @default(cuid())
  conversationId String
  role           String   // user | assistant
  content        String
  /// Citation events emitted with an assistant answer (one per source).
  citations      Json?
  finishReason   String?
  createdAt      DateTime @default(now())

  conversation CompanionConversation @relation(fields: [conversationId], references: [id], onDelete: Cascade)

  @@index([conversationId, createdAt])
  @@map("CompanionMessage")
}
```

Migration `backend/prisma/migrations/<timestamp>_companion_chat_history/migration.sql`, in the same re-runnable style as the existing migrations:

```sql
CREATE TABLE IF NOT EXISTS "CompanionConversation" (
    "id" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "title" TEXT NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,
    CONSTRAINT "CompanionConversation_pkey" PRIMARY KEY ("id")
);

CREATE TABLE IF NOT EXISTS "CompanionMessage" (
    "id" TEXT NOT NULL,
    "conversationId" TEXT NOT NULL,
    "role" TEXT NOT NULL,
    "content" TEXT NOT NULL,
    "citations" JSONB,
    "finishReason" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "CompanionMessage_pkey" PRIMARY KEY ("id")
);

CREATE INDEX IF NOT EXISTS "CompanionConversation_userId_updatedAt_idx" ON "CompanionConversation"("userId", "updatedAt");
CREATE INDEX IF NOT EXISTS "CompanionMessage_conversationId_createdAt_idx" ON "CompanionMessage"("conversationId", "createdAt");

DO $$ BEGIN
  ALTER TABLE "CompanionConversation" ADD CONSTRAINT "CompanionConversation_userId_fkey"
    FOREIGN KEY ("userId") REFERENCES "User"("id") ON DELETE CASCADE ON UPDATE CASCADE;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
  ALTER TABLE "CompanionMessage" ADD CONSTRAINT "CompanionMessage_conversationId_fkey"
    FOREIGN KEY ("conversationId") REFERENCES "CompanionConversation"("id") ON DELETE CASCADE ON UPDATE CASCADE;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
```

`PrismaModule` is `@Global()`, so `CompanionModule` needs no new import. Inject `PrismaService` into `CompanionService`.

### 3.2 Backend: `CompanionService.proxyChat`

1. Check `companion.baseUrl` before any DB writes (keep the existing 503).
2. Resolve the conversation:
   - If `dto.conversation_id` is set, look it up with `findFirst({ where: { id, userId: user.userId } })`. If none, return 404 `{ error: { code: 'not_found', field: 'conversation_id', ... } }` and do not call the companion.
   - Otherwise create one titled from the first question (collapse whitespace, cap ~80 chars with `…`).
3. Load history from the DB, **not** the request: last 20 messages with non-empty content, `orderBy createdAt desc`, then reverse to oldest first. Trim each `content` to 8192 chars (the companion's `HistoryTurn` limit; a 2048-token answer can exceed it).
4. Save the user message.
5. Call companion `/chat` with the real `conversation_id` and the DB `history`.
6. On a 200 stream:
   - Set the header `X-Conversation-Id`. If the frontend reads it cross-origin, add it to `exposedHeaders` in `main.ts` (`enableCors`, which only exposes `Content-Disposition` today).
   - Also write a first SSE frame so the frontend doesn't depend on CORS: `event: conversation\ndata: {"conversation_id":"..."}\n\n`
   - Replace `pipeline(nodeReadable, res)` with a loop that writes each chunk to `res` **and** feeds an SSE parser. Respect backpressure: if `res.write()` returns false, `await once(res, 'drain', { signal: abort.signal })`.
7. In `finally`, if streaming started, save the assistant message:
   - `content` = concatenated `token` event text (fall back to unnamed shim `data: {"text"}` frames only if no named tokens were seen).
   - `citations` = the array of `citation` event payloads.
   - `finishReason` = `done.finish_reason`, else `'cancelled'` if the client aborted, else `'error'`.
   - Skip the insert if content is empty. Always bump `conversation.updatedAt`.
   - Catch and log save errors; never fail the response because of them.

Mark `ChatRequestDto.history` as ignored (keep the field so older clients still validate).

Small SSE parser (`sse-accumulator.ts`): buffer with a streaming `TextDecoder`, split on newlines, track `event:` / `data:` lines, flush on a blank line, ignore `:` comment lines and `[DONE]`.

### 3.3 Backend: conversation endpoints

On `CompanionController` (all `JwtAuthGuard`, all scoped to `user.userId`):

| Route | Behavior |
| --- | --- |
| `GET /chat/conversations` | Latest 50 by `updatedAt desc`: `id, title, createdAt, updatedAt` |
| `GET /chat/conversations/:id` | Conversation plus messages oldest first (`id, role, content, citations, finishReason, createdAt`), 404 if not the user's |
| `DELETE /chat/conversations/:id` | `deleteMany({ where: { id, userId } })`, 404 if count is 0, returns 204 |

### 3.4 Frontend: `api/companionChat.ts`

- Add `ConversationEvent = { conversation_id: string }` and an optional `onConversation` handler. Handle `name === 'conversation'` in `consumeCompanionSse`.
- Add conversation API calls using `apiClient` (as `api/terms.ts` does): `list()`, `get(id)`, `remove(id)`.
- Add a helper that dedupes citations by `source_id` for chip display (used by section 2).

### 3.5 Frontend: `pages/CompanionChat.tsx`

- Keep `conversationId` in state. Send `{ query, conversation_id: conversationId }` and stop building `history` client-side.
- On the `conversation` event, set `conversationId` and refresh the conversation list.
- Conversation list (sidebar on large screens): **New chat** (clears messages and `conversationId`), click to load a conversation (abort any active stream first, map stored messages into `ChatMessage`), and delete (reset the view if it was the open one).

### 3.6 Tests

- SSE parser: tokens split across chunks, shim fallback, multi-byte characters split across chunks.
- `proxyChat`: creates a conversation and saves both turns; sends stored history oldest first and ignores client history; returns 404 for someone else's conversation without calling the companion.
- `deleteConversation` only deletes the user's own conversation.

## 4. Rotate `COMPANION_INTERNAL_SECRET`

The live value was pasted into a chat, so treat it as exposed.

The companion code accepts a second, previous value (`COMPANION_INTERNAL_SECRET_PREVIOUS`), but its ECS task definition only injects `COMPANION_INTERNAL_SECRET` today. Pick one:

- **Simple (a minute or two of chat errors on dev):** put a new value in the `cht-dev-companion-bff-auth` secret (and the prod one), force a new deployment of the companion service, then update the platform backend's companion secret (`companion.internalSecret` in config) to the same value and redeploy it.
- **No downtime:** first add `COMPANION_INTERNAL_SECRET_PREVIOUS` to the companion task definition (`infrastructure/terraform/modules/compute/ecs-companion/main.tf`) holding the old value, deploy, rotate the main secret, update the platform, then remove the previous value.

cht-reports also sends this secret to `/generate`; update it at the same time as the platform.

## 5. Planned: Cognito M2M for platform → companion

On hold until the current deploy is done. It would replace the shared secret entirely.

- **Cognito (platform repo, `infrastructure/terraform/modules/security/cognito/main.tf`):** add `aws_cognito_resource_server "companion"` with scopes `chat.invoke`, `admin`, and `generate.invoke` (or an `llm` resource server if `/generate` moves to a separate gateway). Grant `companion/chat.invoke` and `companion/admin` to the existing `platform_m2m` client; give cht-reports its own client with `generate.invoke`.
- **Platform backend:** `CognitoM2mTokenService` caches one token for the Hub scopes. Make it cache per scope string, request `companion/chat.invoke companion/admin`, and send `Authorization: Bearer <token>` on the companion proxy (keep `X-BFF-Auth` during the switch).
- **Companion:** verify the token (signature from the pool's JWKS, `token_use = access`, allowed `client_id`, required scope), with a mode flag `secret | either | m2m`.
- **Rollout:** Cognito apply → companion in `either` mode → platform sends Bearer → companion in `m2m` mode → delete the bff-auth secret.

## Rollout order

1. Rotate the secret (section 4). Can happen any time.
2. Deploy cht-companion: KB Lambdas, then the service (migration `003_chunks_text_search.sql` runs on startup). Enable Cohere Rerank 3.5 in the Bedrock console and apply Terraform for `bedrock:Rerank`. The first enqueue run embeds all catalog clips; upload `site/*.md` to the raw bucket after the embed Lambda is live.
3. Deploy the platform: chips (section 2) can ship on their own; chat history needs the Prisma migration with the backend, then the frontend.
4. Watch the companion `chat_retrieval` logs (`top_distance`, `top_rerank_score`) to tune `RETRIEVAL_MAX_DISTANCE` (default 0.8) and `RERANK_MIN_SCORE` (default 0.1).

## Other repos (not platform)

- **cht-content-hub:** set `rds_instance_class = "db.t3.small"` in `infrastructure/terraform/environments/variables/dev.github.tfvars`. The dev DB was switched from `db.t4g.small` to get around an AWS capacity shortage, and the next apply would switch it back.
- **cht-util-lambdas:** `dev-lightswitch-on` logs a failed RDS start and moves on. Check that each DB reached `available`, retry on `InsufficientDBInstanceCapacity`, and alert if it still fails.
