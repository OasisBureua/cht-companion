# CHT Platform ↔ Companion chat integration

**Audience:** cht-platform-tool (NestJS BFF + React `/app/chatbot`)  
**Companion service:** this repo (`cht-companion` FastAPI on ECS)  
**Transport:** Server-Sent Events (SSE)  
**Auth split:** Cognito/session only on the BFF; companion trusts `X-BFF-Auth`

This is the contract for building the BFF proxy and streaming answers into the UI.

---

## 1. Request path

```
Browser (logged-in member)
  └─ POST /api/chat   (same-origin, Cognito / session cookie)
       └─ NestJS BFF
            • validate session
            • rate-limit (optional; companion also rate-limits)
            • SSE-proxy (do not buffer the body)
            └─ POST http://cht-companion:8080/chat
                 (ECS Service Connect DNS)
                 headers: X-BFF-Auth, X-User-Id, X-Request-Id, …
```

| Surface | Who calls it | Auth |
|---------|--------------|------|
| `POST /api/chat` | Browser / React | Cognito / platform session |
| `POST /chat` | NestJS only | Shared secret `X-BFF-Auth` |

The browser **must not** call companion directly. Guests see a sign-in CTA; no anonymous chat in v1.

---

## 2. BFF public API (cht-platform-tool)

### `POST /api/chat`

Same JSON body and SSE event model as companion (below). BFF may:

- Reject unauthenticated callers with platform-standard `401` / redirect.
- Attach companion headers from the session (`X-User-Id`, `X-User-Role`, …).
- Forward or generate `X-Request-Id` (ULID preferred) for log correlation.
- Optionally map companion JSON errors into platform error envelopes **before** the stream starts (non-2xx). Once `200` + `text/event-stream` starts, errors arrive as SSE `event: error`.

**Response**

| Header | Value |
|--------|--------|
| `Content-Type` | `text/event-stream` |
| `Cache-Control` | `no-cache` |
| `Connection` | `keep-alive` |
| `X-Accel-Buffering` | `no` (if behind nginx) |
| `X-Request-Id` | Echo companion / BFF request id |

Do **not** set `Transfer-Encoding` buffering that waits for the full body. Flush chunks as they arrive.

---

## 3. Companion internal API

### Endpoint

```
POST /chat
Host: cht-companion:8080   (Service Connect; port 8080)
Content-Type: application/json
Accept: text/event-stream
```

### Headers (BFF → companion)

| Header | Required | Description |
|--------|----------|-------------|
| `X-BFF-Auth` | **Yes** (when secret configured) | Shared secret from Secrets Manager (`COMPANION_INTERNAL_SECRET`) |
| `X-Request-Id` | Recommended | Correlation id; companion generates one if missing |
| `X-User-Id` | Recommended | Cognito `sub` or platform user id (rate-limit key) |
| `X-Session-Id` | Optional | Browser / app session id |
| `X-User-Role` | Optional | e.g. `member`, `admin` (admin routes only) |
| `X-Client` | Optional | e.g. `web`, `bubble` |

### Request body

```json
{
  "query": "What is community health media?",
  "conversation_id": null,
  "history": [
    { "role": "user", "content": "Hello" },
    { "role": "assistant", "content": "Hi — how can I help?" }
  ],
  "options": {
    "max_tokens": 1024,
    "temperature": 0.2
  }
}
```

| Field | Type | Rules |
|-------|------|--------|
| `query` | string | Required, 1–4000 chars |
| `conversation_id` | string \| null | Optional; companion does not persist threads in v1 — UI/BFF may track |
| `history` | array | Max **20** turns; older trimmed server-side; each `content` ≤ 8192 |
| `options.max_tokens` | int | 1–2048, default 1024 |
| `options.temperature` | float | 0–2, default 0.2 |

Unknown fields are ignored (forward-compatible).

### Non-stream errors (before SSE starts)

JSON body shape:

```json
{
  "error": {
    "code": "validation",
    "message": "…",
    "field": "query",
    "retry_after_ms": null
  }
}
```

| HTTP | `error.code` | When |
|------|--------------|------|
| 400 | `validation` | Bad / empty body |
| 401 | `unauthorized` | Missing/invalid `X-BFF-Auth` |
| 429 | `rate_limited` | Too many chat calls (`Retry-After` header set) |
| 503 | `internal` | Dependency hard-down (e.g. rate-limit store in prod) |

---

## 4. SSE event contract

Successful chat returns **`200`** with `Content-Type: text/event-stream`.

Companion emits **named events** (preferred for the new UI) plus a **stub-era shim** so older clients that only read unnamed `data:` lines still work.

### Event order (typical)

1. Zero or more `citation` (sources used for the answer)
2. Zero or more `token` (answer text deltas)
3. Optional mid-stream `error` (e.g. retrieval degraded — non-terminal; or LLM failure — terminal)
4. Exactly one `done` (always; even after a terminal generation error)
5. Shim: unnamed `data: [DONE]`

### Wire format

```
event: citation
data: {"citation_id":"c1","source_id":"…",…}

event: token
data: {"text":"Hello","index":0}

data: {"text":"Hello"}

event: done
data: {"finish_reason":"complete",…}

data: [DONE]
```

### `citation`

```ts
type CitationEvent = {
  citation_id: string;      // e.g. "c1" — matches inline [c1] in answer text
  source_id: string;
  chunk_id: string;
  source_type: "youtube_caption" | "catalog_clip" | "curated_doc" | string;
  title: string;
  url: string;              // deep link (may include &t= for video)
  playlist_url: string | null;
  snippet: string;
  timestamp: number | null; // seconds, if video
};
```

**UI:** Show a citation list / chips; link `url`. Map `[c1]` in streamed markdown to the matching `citation_id`.

### `token`

```ts
type TokenEvent = {
  text: string;   // append to the assistant message
  index: number;  // 0-based delta index
};
```

**UI:** Concatenate `text` in order. Prefer named `event: token`; ignore duplicate shim lines if you already handled the named event.

### `error` (in-stream)

```ts
type ErrorEvent = {
  code:
    | "rate_limited"
    | "retrieval_failed"
    | "retrieval_degraded"
    | "llm_refused"
    | "llm_timeout"
    | "internal"
    | "validation"
    | "unauthorized";
  message: string;
  retryable: boolean;
  retry_after_ms?: number | null;
};
```

| Code | Terminal? | UI behavior |
|------|-----------|-------------|
| `retrieval_degraded` | No | Banner: “answering without KB context”; keep streaming tokens |
| `llm_timeout` / `llm_refused` / `internal` | Yes | Stop appending tokens; show error; still wait for `done` |
| `rate_limited` | Usually pre-stream 429 | If seen in-stream, show retry messaging |

### `done`

```ts
type DoneEvent = {
  finish_reason: "complete" | "truncated" | "error" | "cancelled";
  tokens_generated: number;
  citations_emitted: number;
  latency_ms: {
    retrieval: number;
    first_token: number;
    total: number;
  };
  request_id: string;
};
```

**UI:** Mark the message finished; optionally show truncated state when `finish_reason === "truncated"`.

### Shim (compat)

| Line | Meaning |
|------|---------|
| `data: {"text":"…"}` | Same text as the preceding `token` event |
| `data: [DONE]` | Stream finished (after `done`) |

New React UI should key off **named events** and treat shim as optional.

---

## 5. NestJS BFF implementation notes

### Proxy checklist

1. Auth guard on `POST /api/chat`.
2. `fetch` / `http` to `http://cht-companion:8080/chat` with:
   - `X-BFF-Auth: process.env.COMPANION_INTERNAL_SECRET`
   - `X-User-Id`, `X-Request-Id`, …
3. On companion non-2xx: parse JSON `error`, map to HTTP response, **do not** start SSE.
4. On 200: set SSE response headers, pipe `response.body` to the client **without** collecting it into a string.
5. On client disconnect: abort the upstream request (`AbortController`).
6. Do not JSON-parse the stream as one object; forward bytes or re-emit events.

### Env (platform)

| Variable | Purpose |
|----------|---------|
| `COMPANION_BASE_URL` | e.g. `http://cht-companion:8080` |
| `COMPANION_INTERNAL_SECRET` | Same value as companion Secrets Manager secret |

### Pseudo-code (Nest)

```ts
@Post('chat')
@Header('Content-Type', 'text/event-stream')
async chat(@Req() req, @Res() res, @Body() body: ChatRequestDto) {
  const upstream = await fetch(`${process.env.COMPANION_BASE_URL}/chat`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
      'X-BFF-Auth': process.env.COMPANION_INTERNAL_SECRET!,
      'X-User-Id': req.user.sub,
      'X-User-Role': req.user.role ?? 'member',
      'X-Request-Id': req.id,
      'X-Client': 'web',
    },
    body: JSON.stringify(body),
    signal: req.abortSignal, // cancel when browser disconnects
  });

  if (!upstream.ok || !upstream.body) {
    const err = await upstream.json();
    return res.status(upstream.status).json(err);
  }

  res.setHeader('Cache-Control', 'no-cache');
  res.setHeader('X-Accel-Buffering', 'no');
  res.setHeader('X-Request-Id', upstream.headers.get('X-Request-Id') ?? req.id);
  // pipe ReadableStream → res (framework-specific)
}
```

---

## 6. React UI (`/app/chatbot`) — consume the stream

### Client call

```ts
const res = await fetch('/api/chat', {
  method: 'POST',
  credentials: 'include',
  headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
  body: JSON.stringify({ query, history, conversation_id }),
});

if (!res.ok) {
  const { error } = await res.json();
  throw error; // { code, message, … }
}
```

### Parse SSE

Use `EventSource` only if you can POST (browsers cannot). Prefer `fetch` + `ReadableStream` + an SSE parser (e.g. `@microsoft/fetch-event-source`, or a small line splitter).

Recommended handler:

```ts
type UiHandlers = {
  onCitation: (c: CitationEvent) => void;
  onToken: (t: TokenEvent) => void;
  onError: (e: ErrorEvent) => void;
  onDone: (d: DoneEvent) => void;
};

// For each SSE frame:
//   event name defaults to "message" if omitted
//   if name === "citation" → JSON.parse(data) as CitationEvent
//   if name === "token"    → append text
//   if name === "error"    → surface banner / stop on terminal codes
//   if name === "done"     → finalize message
//   if data === "[DONE]"   → ignore if done already handled
//   if unnamed + JSON {"text"} → only use if you are not handling named token
```

### UX mapping

| Stream signal | UI |
|---------------|-----|
| First `citation` | Open “Sources” panel / chips |
| Each `token` | Append to assistant bubble (markdown-friendly) |
| `retrieval_degraded` | Soft warning, continue |
| Terminal `error` | Error state on bubble |
| `done` | Stop spinner; enable send again |
| Abort / navigate away | `AbortController.abort()` |

Keep `history` in client state (last ≤ 20 turns) and send it on each turn until companion persists conversations.

---

## 7. Health (ops / readiness)

Companion (internal):

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/live` | Process up |
| GET | `/ready` | DB + Bedrock probe |
| GET | `/health` | Aggregate status + `checks.database` / `checks.bedrock` |

BFF can expose a thin wrapper or rely on ECS health checks; the chat UI does not need to call these.

---

## 8. Models & infra assumptions (companion)

| Concern | Value |
|---------|--------|
| Chat LLM | Bedrock Claude — `us.anthropic.claude-sonnet-5` |
| Embeddings | `amazon.titan-embed-text-v2:0` (1024-d) |
| Companion auth | IAM task role for Bedrock (no Anthropic API key) |
| Network | Private Service Connect only |

---

## 9. Platform checklist

- [ ] Secrets Manager / env: `COMPANION_INTERNAL_SECRET` on NestJS **and** companion ECS
- [ ] `COMPANION_BASE_URL=http://cht-companion:8080` (dev/prod Service Connect name)
- [ ] NestJS `POST /api/chat` SSE proxy (no body buffering)
- [ ] Cognito/session guard + guest CTA
- [ ] React `/app/chatbot` (+ bubble): named SSE events, citations, abort on leave
- [ ] Retire iframe + `GET /api/auth/chatbot-token` after cutover
- [ ] Dev smoke: authenticated `POST /api/chat` → tokens + `done` in browser Network tab

---

## 10. Example stream (abbreviated)

```
event: citation
data: {"citation_id":"c1","source_id":"curated:hello-world","chunk_id":"…","source_type":"curated_doc","title":"Hello World","url":"https://communityhealth.media/","playlist_url":null,"snippet":"…","timestamp":null}

event: token
data: {"text":"Community ","index":0}

data: {"text":"Community "}

event: token
data: {"text":"health media…","index":1}

data: {"text":"health media…"}

event: done
data: {"finish_reason":"complete","tokens_generated":2,"citations_emitted":1,"latency_ms":{"retrieval":42,"first_token":380,"total":1200},"request_id":"01H…"}

data: [DONE]
```

---

## Related

- Architecture: [chmbot-migration-architecture.md](./chmbot-migration-architecture.md)
- Companion types: `backend/api/schemas/models.py`
- Stream emitter: `backend/api/sse.py`
- Route: `backend/api/routers/chat.py`
