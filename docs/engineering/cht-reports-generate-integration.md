# cht-reports ↔ Companion /generate integration

**Audience:** cht-reports (NestJS report-generation orchestration service)
**Companion service:** this repo (`cht-companion` FastAPI on ECS)
**Transport:** plain HTTPS, single JSON request/response (not SSE)
**Auth:** shared secret `X-BFF-Auth`, same mechanism and secret as the chat integration

This is the contract for cht-reports calling into companion to generate report content. Distinct from `/chat` (see [cht-platform-chat-integration.md](./cht-platform-chat-integration.md)): no retrieval, no chat history, no hardcoded system prompt. The caller supplies both directly and gets back one complete response, not a token stream.

---

## 1. Request path

```
cht-reports (ECS, on-demand orchestration)
  • pulls its own input packet from Content Hub (transcript + survey data)
  • assembles a report-specific system prompt + user content
  └─ POST http://cht-companion:8080/generate
       (ECS Service Connect DNS, same shared namespace/cluster
        cht-platform-tool and cht-companion already join)
       headers: X-BFF-Auth
```

Both services live on the same shared Service Connect namespace (`cht-dev.local` / `cht.local`). See cht-reports' `infrastructure/terraform/modules/compute/ecs-cluster`, which joins that namespace via data-source lookups rather than creating its own.

---

## 2. Why not /chat

`/chat` does retrieval (vector search against the chat knowledge base) plus generation together, keyed on a `query` string. Report generation assembles its own context (a specific campaign's transcript and survey responses, pulled from Content Hub) and has no use for the chat knowledge base; forcing it through `/chat` would search the wrong corpus. `/generate` gives a caller with its own context a plain completion call.

---

## 3. Endpoint

```
POST /generate
Host: cht-companion:8080   (Service Connect; port 8080)
Content-Type: application/json
```

### Headers (cht-reports → companion)

| Header | Required | Description |
|--------|----------|-------------|
| `X-BFF-Auth` | **Yes** (when secret configured) | Same shared secret as `/chat`, from Secrets Manager (`COMPANION_INTERNAL_SECRET`) |
| `X-Client` | Recommended | Caller identity, used as the rate-limit bucket key (`cht-reports` sends `X-Client: cht-reports`). Falls back to a shared `unknown-caller` bucket if omitted; the request still succeeds, it just shares quota with any other caller that also omits it. |

No `X-User-Id`, `X-Session-Id`, or `X-User-Role`. This is a service-to-service call, not a per-end-user one.

### Request body

```json
{
  "system_prompt": "You are generating an Executive Summary report...",
  "user_content": "Transcripts:\n...\n\nSurvey responses:\n...",
  "max_tokens": 4096,
  "temperature": null
}
```

| Field | Type | Rules |
|-------|------|--------|
| `system_prompt` | string | Required, 1–8000 chars |
| `user_content` | string | Required, 1–100000 chars (a full transcript and survey packet can be large) |
| `max_tokens` | int | 1–8192, default 4096. Higher ceiling than `/chat`'s 2048; a report is a complete document, not a chat turn. |
| `temperature` | float \| null | 0–2, omitted by default. Claude Sonnet 5 rejects `temperature`; only pass it for models that accept it. |

Unknown fields are ignored (forward-compatible).

### Success response

```json
{
  "text": "Executive Summary...",
  "finish_reason": "complete",
  "request_id": "01H..."
}
```

| Field | Type | Notes |
|-------|------|-------|
| `text` | string | The complete generated text, not streamed; the whole response in one call |
| `finish_reason` | `"complete" \| "truncated" \| "error" \| "cancelled"` | Same enum as `/chat`'s `done.finish_reason` |
| `request_id` | string | ULID, for log correlation on both sides |

### Error response

Same shape as `/chat`:

```json
{
  "error": {
    "code": "llm_timeout",
    "message": "...",
    "retry_after_ms": null
  }
}
```

| HTTP | `error.code` | When |
|------|--------------|------|
| 400 | `validation` | Bad or empty body |
| 401 | `unauthorized` | Missing or invalid `X-BFF-Auth` |
| 429 | `rate_limited` | Too many `/generate` calls (`Retry-After` header set) |
| 502 | `llm_timeout` | Bedrock call itself failed (throttling, timeout, malformed response) |
| 503 | `internal` | Rate-limit store hard-down (prod only; dev fails open) |

---

## 4. cht-reports client implementation

`backend/src/bedrock/bedrock.client.ts` in cht-reports. What it does:

1. `POST` to `${COMPANION_SERVICE_CONNECT_URL}/generate` (`COMPANION_SERVICE_CONNECT_URL` defaults to `http://cht-companion:8080`).
2. Sends `X-BFF-Auth: ${COMPANION_INTERNAL_SECRET}` and `X-Client: cht-reports`.
3. On non-2xx: parses the `{"error": {...}}` body if present and throws `BedrockGenerationError` with the real message, falling back to a generic `HTTP <status>` message if the error body isn't valid JSON.
4. On 2xx: returns `{ text, finishReason }`.

### Env (cht-reports)

| Variable | Purpose |
|----------|---------|
| `COMPANION_SERVICE_CONNECT_URL` | e.g. `http://cht-companion:8080` |
| `COMPANION_INTERNAL_SECRET` | Same plaintext as companion's Secrets Manager secret |

**Companion secret (this repo's Terraform, `modules/security/bff-auth`):**

| Env | Secret name |
|-----|-------------|
| development | `cht-dev-companion-bff-auth` |
| prod | `cht-companion-bff-auth` |

cht-reports' own Terraform references this secret via `data "aws_secretsmanager_secret"` rather than a managed resource; lifecycle stays owned here. It grants its execution role `secretsmanager:GetSecretValue` on the secret plus `kms:Decrypt` on companion's shared KMS key (`alias/cht-dev-companion` / `alias/cht-companion`). See cht-reports' `infrastructure/terraform/environments/us-east-1/main.tf`, `data.aws_secretsmanager_secret.companion_bff_auth` and `data.aws_kms_alias.companion`.

---

## 5. Rate limits

Separate bucket from `/chat`'s per-user limits, keyed by caller identity rather than `X-User-Id`:

| Env var | Default | Notes |
|---------|---------|-------|
| `RATE_LIMIT_GENERATE_PER_MINUTE` | 5 | Report generation is bulk/background work, not an interactive chat turn. A runaway caller here burns real Bedrock spend fast given the larger `max_tokens` ceiling. |
| `RATE_LIMIT_GENERATE_PER_DAY` | 200 | |

Same fail-open(dev)/fail-closed(prod) policy as `/chat` when the Redis-backed rate-limit store is unreachable. Bucket key is the caller-supplied `X-Client` header; `bedrock.client.ts` sends `X-Client: cht-reports`.

---

## 6. Models and infra assumptions

Same as `/chat`; see [cht-platform-chat-integration.md §8](./cht-platform-chat-integration.md#8-models--infra-assumptions-companion). `/generate` uses the same Bedrock client, model id, and IAM task role. No separate Bedrock provisioning is needed.

---

## 7. Not yet handled

- **No streaming.** `/generate` is a single blocking call. A report-length response can take a while; cht-reports' orchestration is already async (SQS-driven, not a synchronous HTTP request from an end user), so this is an acceptable tradeoff. Worth revisiting if `/generate` ever gets a second caller with different latency needs.
- **No structured output parsing.** `/generate` returns raw text. Extracting headlines, bullets, and sections from that text is cht-reports' own responsibility (see `report-generation.orchestrator.ts`'s `parseGeneratedSections`, currently a placeholder). The prior MediaHub report pipeline has real section-parsing logic worth porting when this is needed.

---

## Related

- Chat integration, the sibling contract `/generate` diverges from: [cht-platform-chat-integration.md](./cht-platform-chat-integration.md)
- Bedrock client, shared by both `/chat` and `/generate`: `backend/api/bedrock.py`
- Route: `backend/api/routers/generate.py`
- Schemas: `backend/api/schemas/models.py` (`GenerateRequest`, `GenerateResponse`)
- cht-reports client: `cht-reports/backend/src/bedrock/bedrock.client.ts`
