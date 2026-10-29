# Bedrock Access Gateway (extended)

> Based on [aws-samples/bedrock-access-gateway](https://github.com/aws-samples/bedrock-access-gateway), with added USAGE logging, prompt caching controls, adaptive thinking support, tool-call streaming fixes and inference profile filtering.

> [!IMPORTANT]
> **Upstream is deprecated.** Amazon Bedrock now serves OpenAI-compatible and
> Anthropic-compatible APIs natively. See [Migrating to native Amazon Bedrock APIs](#migrating-to-native-amazon-bedrock-apis) below.

## Upstream

The [Bedrock Access Gateway](https://github.com/aws-samples/bedrock-access-gateway) project by AWS Samples provides an OpenAI-compatible API proxy for Amazon Bedrock, enabling drop-in replacement for applications built against the OpenAI SDK.

---

## Features

### 1. Prompt Caching Schema Support

Adds support for [Anthropic-style prompt caching](https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching) through the OpenAI-compatible API. Clients can send structured system/developer messages with `cache_control` markers, which are translated to Bedrock's `cachePoint` blocks.

- `CacheControl` model and `cache_control` field on `TextContent`
- `SystemMessage.content` and `DeveloperMessage.content` accept `str | list[TextContent]`
- `_parse_system_prompts` handles list-format content with cache markers
- `_parse_content_parts` emits `cachePoint` blocks after marked content

**Files:** `src/api/schema.py`, `src/api/models/bedrock.py`

---

### 2. Configurable DEFAULT_MAX_TOKENS

The default `max_tokens` value is configurable via environment variable. `effective_max_tokens` prefers `max_completion_tokens` over `max_tokens`.

| Variable | Default | Description |
|----------|---------|-------------|
| `DEFAULT_MAX_TOKENS` | `2048` | Default max tokens when not specified in the request |

**Files:** `src/api/setting.py`, `src/api/schema.py`, `src/api/models/bedrock.py`

---

### 3. USAGE Logging & Log Levels

Three-tier logging (INFO → DEBUG → TRACE) with a per-request USAGE line at INFO level.

- Custom TRACE level (5) below DEBUG (10) for per-chunk streaming logs, defined in `setting.py`
- Debug and trace output uses lazy `%s` formatting; expensive operations are guarded with `isEnabledFor`
- Request structure summaries (message counts, roles, block types, tool IDs) are logged at DEBUG; message content previews only at TRACE
- ECS/Fargate-aware log format: timestamps and level are omitted when `ECS_CONTAINER_METADATA_URI` is set (CloudWatch adds its own)
- INFO-level USAGE log line per request: user, chat, model, tokens in/out/cache, user-agent
- Configurable header extraction for user/chat attribution
- Only the `api` logger hierarchy gets DEBUG/TRACE; boto3/botocore/urllib3 stay at INFO

| Variable | Default | Description |
|----------|---------|-------------|
| `DEBUG` | `false` | Enable DEBUG-level logging for the `api` loggers |
| `TRACE` | `false` | Enable TRACE-level logging (below DEBUG) for per-chunk streaming details and content previews |
| `USAGE_USER_HEADER` | `""` | HTTP header carrying the user identity for USAGE logging (OpenWebUI: `x-openwebui-user-email`) |
| `USAGE_CHAT_ID_HEADER` | `""` | HTTP header carrying the chat/session ID for USAGE logging (OpenWebUI: `x-openwebui-chat-id`) |

**USAGE log example:**
```
USAGE | user=admin@example.com | chat=abc-123 | model=anthropic.claude-sonnet-4-20250514-v1:0 | max_tokens=4096 | in=1523 | out=847 | cache_write=0 | cache_read=1200 | ua=OpenAI/Python 1.x
```

**Files:** `src/api/setting.py`, `src/api/app.py`, `src/api/routers/chat.py`, `src/api/models/bedrock.py`

---

### 4. Validation Error Logging

The `RequestValidationError` handler logs the request method, path and number of validation errors at WARNING. The rejected request body (first 2000 characters) is logged only at TRACE level.

**Files:** `src/api/app.py`

---

### 5. Tool Call Streaming

Bedrock numbers all content blocks (text, reasoning, tool_use) with a shared `contentBlockIndex` sequence, while the OpenAI API expects 0-based indices across tool calls only.

- **Index mapping:** each streaming request keeps a sequential 0-based `_tool_call_index_map`, independent of Bedrock's content block numbering, so a tool call emitted as the first block gets index 0.
- **Empty arguments:** the initial empty argument delta Bedrock sends before the JSON arguments is skipped. At `contentBlockStop`, a single synthetic `"{}"` is emitted only if no arguments were received, for clients that require non-empty arguments.

**Files:** `src/api/models/bedrock.py`

---

### 6. Non-blocking Streaming and Model Listing

- Each blocking `next()` call on the boto3 event stream runs in `run_in_threadpool`, so the event loop keeps serving other requests (health checks, `GET /models`, other completions) during a streaming response.
- `list_models()` is async and runs `list_bedrock_models()` (paginated boto3 calls) in `run_in_threadpool`.

**Files:** `src/api/models/bedrock.py`, `src/api/routers/model.py`

---

### 7. Inference Profile Region Filtering

`INFERENCE_PROFILE_REGIONS` filters `SYSTEM_DEFINED` inference profiles by geographic prefix. Inference-profile-only models (no `ON_DEMAND` support) are listed via their profile IDs even when `ENABLE_CROSS_REGION_INFERENCE=false`.

- `SYSTEM_DEFINED` profiles are always fetched into `profile_metadata` for feature detection
- Inference-profile-only models are included via their profile IDs regardless of the cross-region setting
- Profiles are filtered by `INFERENCE_PROFILE_REGIONS` prefix (e.g. `au` for `au.*` only, `au,us` for both)
- Empty `INFERENCE_PROFILE_REGIONS` (default) includes all regions

| Variable | Default | Description |
|----------|---------|-------------|
| `INFERENCE_PROFILE_REGIONS` | `""` (all) | Comma-separated region prefixes to filter inference profiles (e.g. `au`, `au,us`) |

**Files:** `src/api/models/bedrock.py`, `src/api/setting.py`

---

### 8. Adaptive Thinking Auto-Detection

Newer Claude models reject the legacy `reasoning_config={type:enabled, budget_tokens:N}` scheme and require `thinking={type:adaptive}` + `output_config={effort:...}` instead. The gateway detects Bedrock's validation error message and retries once with the adaptive scheme, so no model list needs maintaining.

- Models that require adaptive thinking are recorded in an in-process runtime cache (`ADAPTIVE_THINKING_MODELS`); later requests to those models use the adaptive scheme directly
- Adaptive thinking requests include `display: "summarized"`, which is required for Bedrock to return non-empty reasoning text
- OpenAI `reasoning_effort` maps to the Bedrock `effort` parameter for adaptive models

**Files:** `src/api/models/bedrock.py`

---

### 9. Prompt Caching Deduplication

With `ENABLE_PROMPT_CACHING=true`, server-side `cachePoint` injection is skipped when the request already contains `cache_control` markers, so requests never carry duplicate `cachePoint` blocks (Bedrock allows 4 checkpoints per request, and duplicates add cache-write cost).

- Clients that send `cache_control` markers: their markers are used as-is
- Clients that send none: the server injects `cachePoint` blocks for system prompts and the last user message
- `extra_body.prompt_caching` per-request overrides take precedence over `ENABLE_PROMPT_CACHING`

**Files:** `src/api/models/bedrock.py`
**Tests:** `test/test_cache_point_dedup.py`

---

### 10. Prompt Caching Model Gating

Only some models (Claude, Nova) support prompt caching; others (e.g. Qwen, DeepSeek, Llama) reject `cachePoint` with `AccessDeniedException: did not allow prompt caching`.

1. **Proactive:** `_parse_content_parts()` and `_parse_system_prompts()` check `_supports_prompt_caching()` before converting `cache_control` → `cachePoint`. Markers are dropped for unsupported models.
2. **Reactive:** if a model rejects caching, `_invoke_bedrock()` strips all `cachePoint` blocks via `_strip_cache_points()`, retries the request, and adds the model to the runtime `NO_CACHE_MODELS` set so later requests skip caching.

**Files:** `src/api/models/bedrock.py`
**Tests:** `test/test_cache_model_gating.py`

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DEFAULT_MAX_TOKENS` | `2048` | Default max tokens when not specified in request |
| `DEBUG` | `false` | Enable DEBUG-level logging (request structure summaries) |
| `TRACE` | `false` | Enable TRACE-level logging below DEBUG |
| `USAGE_USER_HEADER` | `""` | HTTP header carrying the user identity in USAGE logs (OpenWebUI: `x-openwebui-user-email`) |
| `USAGE_CHAT_ID_HEADER` | `""` | HTTP header carrying the chat/session ID in USAGE logs (OpenWebUI: `x-openwebui-chat-id`) |
| `INFERENCE_PROFILE_REGIONS` | `""` (all) | Comma-separated region prefixes to filter inference profiles |
| `ENABLE_PROMPT_CACHING` | `false` | Enable server-side prompt caching; skipped when the request already contains `cache_control` markers |

---

## Setup

```bash
git clone https://github.com/bluecrystalsolutions/bedrock-access-gateway.git
cd bedrock-access-gateway
git checkout my-contributions

pip install -r src/requirements.txt
cd src && API_KEY=<your-key> uvicorn api.app:app --host 127.0.0.1 --port 8000
```

## Migrating to native Amazon Bedrock APIs

Point your SDK at the [`bedrock-mantle`](https://docs.aws.amazon.com/bedrock/latest/userguide/endpoints.html) endpoint:

- **Claude models** — native [Anthropic Messages API](https://docs.aws.amazon.com/bedrock/latest/userguide/inference-messages-api.html), so the Anthropic SDKs work unchanged.
- **GPT and other first- and third-party models** — OpenAI-compatible [Chat Completions](https://docs.aws.amazon.com/bedrock/latest/userguide/inference-chat-completions-mantle.html) and [Responses](https://docs.aws.amazon.com/bedrock/latest/userguide/bedrock-mantle.html) APIs, so the OpenAI SDKs work unchanged.

Beyond replacing this proxy, `bedrock-mantle` adds per-application [cost attribution](https://docs.aws.amazon.com/bedrock/latest/userguide/cost-mgmt-projects.html), server-side tools, background inference and higher throughput limits. See [Endpoints supported by Amazon Bedrock](https://docs.aws.amazon.com/bedrock/latest/userguide/endpoints.html) to compare it with `bedrock-runtime`.

## Security

See the [Security Guide](./docs/Security.md) for how to enable HTTPS on the ALB and how to configure the
controls around remote image URL fetching in the multimodal API. If you deployed before those controls
were added, read [If you deployed an earlier version](./docs/Security.md#if-you-deployed-an-earlier-version).

To report a security issue, see [CONTRIBUTING](CONTRIBUTING.md#security-issue-notifications).

## License

Same as upstream — see [LICENSE](LICENSE).
