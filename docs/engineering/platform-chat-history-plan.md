# Platform work for Companion chat history and citations

What cht-platform-tool needs so the Companion RAG changes (history-aware answers, one citation per source) work end to end.

## Where things stand

The cht-companion side is done but not deployed:

- `POST /chat` uses `history` to rewrite follow-up questions into standalone searches, and passes the history into the answer.
- Retrieval is hybrid (vector + Postgres full text), with a distance cutoff and Cohere reranking.
- One `citation` event is sent per **source**, not per chunk.
- `conversation_id` is accepted but not stored. The companion is stateless, so the platform owns history.

The platform today:

- Builds `history` from React state, so it is lost on refresh and the client can send anything.
- Always sends `conversation_id: null`.
- Shows citation chips **above** the answer and dedupes them only by `citation_id`.

## 1. Database (Prisma)

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

Migration `backend/prisma/migrations/<timestamp>_companion_chat_history/migration.sql`, using the same re-runnable style as the existing migrations:

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

## 2. Backend: `CompanionService.proxyChat`

Order of operations:

1. Check `companion.baseUrl` before any DB writes (keep the existing 503).
2. Resolve the conversation:
   - If `dto.conversation_id` is set, look it up with `findFirst({ where: { id, userId: user.userId } })`. If none, return 404 `{ error: { code: 'not_found', field: 'conversation_id', ... } }` and do not call the companion.
   - Otherwise create one with a title from the first question (collapse whitespace, cap ~80 chars with `…`).
3. Load history from the DB, **not** the request: the last 20 messages with non-empty content, `orderBy createdAt desc`, then reverse to oldest first. Trim each `content` to 8192 chars (the companion's `HistoryTurn` limit; a 2048-token answer can exceed it).
4. Save the user message.
5. Call companion `/chat` with `conversation_id` set to the real id and the DB `history`.
6. On a 200 stream:
   - Set the header `X-Conversation-Id`. If the frontend reads it cross-origin, add it to `exposedHeaders` in `main.ts` (`enableCors`).
   - Also write a first SSE frame so the frontend doesn't depend on CORS:
     `event: conversation\ndata: {"conversation_id":"..."}\n\n`
   - Replace `pipeline(nodeReadable, res)` with a loop that writes each chunk to `res` **and** feeds an SSE parser. Respect backpressure: if `res.write()` returns false, `await once(res, 'drain', { signal: abort.signal })`.
7. In `finally`, if streaming started, save the assistant message:
   - `content` = concatenated `token` event text (fall back to unnamed shim `data: {"text"}` frames only if no named tokens were seen).
   - `citations` = the array of `citation` event payloads.
   - `finishReason` = `done.finish_reason`, else `'cancelled'` if the client aborted, else `'error'`.
   - Skip the insert if content is empty. Always bump `conversation.updatedAt`.
   - Catch and log save errors; never fail the response because of them.

Mark `ChatRequestDto.history` as ignored (keep the field so older clients still validate).

Small SSE parser (`sse-accumulator.ts`): buffer text with a streaming `TextDecoder`, split on newlines, track `event:` / `data:` lines, flush on blank line, ignore `:` comment lines and `[DONE]`.

## 3. Backend: conversation endpoints

On `CompanionController` (all `JwtAuthGuard`, all scoped to `user.userId`):

| Route | Behavior |
| --- | --- |
| `GET /chat/conversations` | Latest 50 by `updatedAt desc`: `id, title, createdAt, updatedAt` |
| `GET /chat/conversations/:id` | Conversation plus messages oldest first (`id, role, content, citations, finishReason, createdAt`), 404 if not the user's |
| `DELETE /chat/conversations/:id` | `deleteMany({ where: { id, userId } })`, 404 if count is 0, returns 204 |

## 4. Frontend: `api/companionChat.ts`

- Add `ConversationEvent = { conversation_id: string }` and an optional `onConversation` handler. Handle `name === 'conversation'` in `consumeCompanionSse`.
- Add conversation API calls using `apiClient` (as `api/terms.ts` does): `list()`, `get(id)`, `remove(id)`.
- Add a helper that dedupes citations by `source_id` for chip display.

## 5. Frontend: `pages/CompanionChat.tsx`

- Keep `conversationId` in state. Send `{ query, conversation_id: conversationId }` and stop building `history` client-side.
- On the `conversation` event, set `conversationId` and refresh the conversation list.
- Move citation chips **below** the answer text. Dedupe chips by `source_id` for display, but keep the full citation list in state so inline `[cN]` markers from older answers still resolve to links.
- Conversation list (sidebar on large screens): **New chat** (clears messages and `conversationId`), click to load a conversation (abort any active stream first, map stored messages into `ChatMessage`), and delete (reset the view if it was the open one).

## 6. Tests to add

- SSE parser: tokens split across chunks, shim fallback, multi-byte characters split across chunks.
- `proxyChat`: creates a conversation and saves both turns; sends stored history oldest first and ignores client history; returns 404 for someone else's conversation without calling the companion.
- `deleteConversation` only deletes the user's own conversation.

## 7. Rollout order

1. Deploy cht-companion (migration `003_chunks_text_search.sql` runs on startup). Enable Cohere Rerank 3.5 model access in the Bedrock console and apply Terraform for `bedrock:Rerank`.
2. Deploy the platform backend (Prisma migration), then the frontend.
3. Watch the companion `chat_retrieval` logs (`top_distance`, `top_rerank_score`) to tune `RETRIEVAL_MAX_DISTANCE` (default 0.8) and `RERANK_MIN_SCORE` (default 0.1).
