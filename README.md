# Bedrock Access Gateway — BCS Fork

> Fork of [aws-samples/bedrock-access-gateway](https://github.com/aws-samples/bedrock-access-gateway) with production-grade enhancements for logging, streaming, tool calling, prompt caching, adaptive thinking, and operational resilience.

> [!IMPORTANT]
> **Upstream is deprecated.** Amazon Bedrock now serves OpenAI-compatible and
> Anthropic-compatible APIs natively. See [Migrating to native Amazon Bedrock APIs](#migrating-to-native-amazon-bedrock-apis) below.
> This fork preserves enhancements not available upstream (USAGE logging, prompt caching schema, adaptive thinking, etc.).

## Upstream

This is a fork of the [Bedrock Access Gateway](https://github.com/aws-samples/bedrock-access-gateway) project by AWS Samples. The upstream project provides an OpenAI-compatible API proxy for Amazon Bedrock, enabling drop-in replacement for applications built against the OpenAI SDK.

---

## Fork Enhancements

All enhancements below are on the [`my-contributions`](../../tree/my-contributions) branch. Features marked with a PR number were submitted upstream; others are direct commits to this fork.

### 1. Prompt Caching Schema Support — [PR 230](https://github.com/aws-samples/bedrock-access-gateway/pull/230)

Adds support for [Anthropic-style prompt caching](https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching) through the OpenAI-compatible API. Clients can send structured system/developer messages with `cache_control` markers, which are translated to Bedrock's `cachePoint` blocks.

**What it does:**
- Adds `CacheControl` model and `cache_control` field on `TextContent`
- `SystemMessage.content` and `DeveloperMessage.content` accept `str | list[TextContent]`
- `_parse_system_prompts` handles list-format content with cache markers
- `_parse_content_parts` emits `cachePoint` blocks after marked content

Without this, client-side `cache_control` markers are rejected as unknown fields by the Pydantic schema.

**Files:** `src/api/schema.py`, `src/api/models/bedrock.py`
**Branch:** [`feature/prompt-caching-schema`](../../tree/feature/prompt-caching-schema)
**Commits:** `1d95046`, `d30b7c8`

---

### 2. Configurable DEFAULT_MAX_TOKENS — [PR 228](https://github.com/aws-samples/bedrock-access-gateway/pull/228)

Makes the default `max_tokens` value configurable via environment variable instead of the hardcoded upstream default of 2048. Also introduces `effective_max_tokens` which prefers `max_completion_tokens` over `max_tokens`, eliminating duplicate logic in the request parser.

| Variable | Default | Description |
|----------|---------|-------------|
| `DEFAULT_MAX_TOKENS` | `2048` | Default max tokens when not specified in the request |

**Files:** `src/api/setting.py`, `src/api/schema.py`, `src/api/models/bedrock.py`
**Branch:** [`feature/configurable-max-tokens`](../../tree/feature/configurable-max-tokens)
**Commits:** `14fd3bd`, `484f670`

---

### 3. USAGE Logging & Trace Levels — [PR 226](https://github.com/aws-samples/bedrock-access-gateway/pull/226)

Comprehensive logging overhaul that replaces the binary `if DEBUG: logger.info()` pattern with a three-tier system (INFO → DEBUG → TRACE) and adds per-request USAGE logging at INFO level.

**Key changes:**
- Custom TRACE level (5) below DEBUG (10) for per-chunk streaming logs, centralised in `setting.py`
- All `if DEBUG: logger.info` patterns converted to `logger.debug` or TRACE with lazy `%s` formatting
- Expensive debug operations guarded with `isEnabledFor` checks
- ECS/Fargate-aware log format — omits timestamps and brackets when `ECS_CONTAINER_METADATA_URI` is set (CloudWatch adds its own)
- INFO-level USAGE log line per request: user, chat, model, tokens in/out/cache, user-agent
- Configurable header extraction for user/chat attribution (proxy-agnostic)
- Only `api` logger hierarchy gets DEBUG/TRACE — boto3/botocore/urllib3 stay at INFO

| Variable | Default | Description |
|----------|---------|-------------|
| `TRACE` | `false` | Enable TRACE-level logging (below DEBUG) for per-chunk streaming details |
| `USAGE_USER_HEADER` | `""` | HTTP header to extract user identity for USAGE logging (e.g. `x-openwebui-user-email`) |
| `USAGE_CHAT_ID_HEADER` | `""` | HTTP header to extract chat/session ID for USAGE logging (e.g. `x-openwebui-chat-id`) |

**USAGE log example:**
```
USAGE | user=admin@example.com | chat=abc-123 | model=anthropic.claude-sonnet-4-20250514-v1:0 | max_tokens=4096 | in=1523 | out=847 | cache_write=0 | cache_read=1200 | ua=OpenAI/Python 1.x
```

**Post-merge refinements** (direct commits after PR merge):
- Dropped custom log format to avoid inconsistent CloudWatch output (`bacbb2c`)
- Guarded all debug log calls with `isEnabledFor` to prevent eager `str()` evaluation (`e108671`)
- Simplified validation error handler logging (`cadbb63`)
- Nested profile resolution debug log inside existing guard (`97a74d9`)
- Removed unused import, switched to lazy `%s` formatting (`b094571`)
- Simplified TRACE/DEBUG config; conditional log format for ECS (`e7eb4df`)
- Centralised `TRACE_LEVEL` in `setting.py`, imported everywhere (`d5ddf86`)

**Files:** `src/api/setting.py`, `src/api/app.py`, `src/api/routers/chat.py`, `src/api/models/bedrock.py`
**Branch:** [`feature/logging-overhaul`](../../tree/feature/logging-overhaul)
**Commits:** `26c68c3`, `ac891b4`, `bacbb2c`–`d5ddf86` (7 post-merge refinements)

---

### 4. Enhanced Validation Error Handler

Improves the `RequestValidationError` handler to log the number of validation errors and per-field details (location + message) instead of just the first line of the exception string. Makes it much easier to diagnose which fields failed validation when clients send malformed requests, without exposing sensitive request body data.

**Files:** `src/api/app.py`
**Commits:** `e8f19e3`, `91f9a49`

---

### 5. Tool Call Streaming Fix

Bedrock numbers ALL content blocks (text, reasoning, tool_use) with a shared `contentBlockIndex` sequence, but the OpenAI API expects 0-based indices across tool calls only. This mismatch caused tool calls to silently fail in OpenAI-compatible streaming clients (e.g. pipecat, Roo Code).

**Two bugs fixed:**
1. **Index mapping** — `contentBlockIndex - 1` produced `-1` when the model emits a tool call first (no preceding text block). Fix: track a proper sequential 0-based `_tool_call_index_map` per streaming request, independent of Bedrock's global content block numbering.
2. **Empty arguments** — Bedrock sends an initial empty delta before streaming actual JSON arguments. Converting `""` to `"{}"` on every delta caused concatenation to produce invalid JSON like `{}{"mode":"code",...}`. Fix: skip empty tool argument deltas during streaming; at `contentBlockStop`, emit a single synthetic `"{}"` only if no arguments were received (for clients that require truthy arguments).

**Files:** `src/api/models/bedrock.py`
**Commits:** `d4b9d45`, `76caaf6`

---

### 6. Event Loop Starvation Prevention

`_async_iterate()` was blocking the asyncio event loop because the synchronous `for chunk in stream` fetched each chunk on the main thread before the no-op `run_in_threadpool(lambda: chunk)` was called. This starved all other requests (health checks, GET /models, other chat completions) for the entire duration of a streaming response, causing ALB health check failures and ECS container restarts.

**Fixes:**
- Run each blocking `next()` call inside `run_in_threadpool` so the event loop can serve other requests between stream chunks
- Wrap `list_bedrock_models()` (paginated boto3 API calls) in `run_in_threadpool` and make `list_models()` async, so model listing does not block concurrent request handling

**Files:** `src/api/models/bedrock.py`, `src/api/routers/model.py`
**Commits:** `570522a`

---

### 7. Inference Profile Region Filtering

Adds `INFERENCE_PROFILE_REGIONS` environment variable to filter `SYSTEM_DEFINED` inference profiles by geographic prefix. Also fixes a bug where newer inference-profile-only models (Claude Opus 4.6, Sonnet 4.6, Sonnet 4.5) were invisible when `ENABLE_CROSS_REGION_INFERENCE=false` because they have no `ON_DEMAND` foundation model — only cross-region inference profiles.

**Key changes:**
- Always fetch `SYSTEM_DEFINED` profiles into `profile_metadata` for feature detection, even when `ENABLE_CROSS_REGION_INFERENCE=false`
- Include inference-profile-only models (no `ON_DEMAND`) via their profile IDs regardless of cross-region setting
- Filter profiles by `INFERENCE_PROFILE_REGIONS` prefix (e.g. `au` for `au.*` only, `au,us` for both)
- Empty `INFERENCE_PROFILE_REGIONS` (default) includes all regions

| Variable | Default | Description |
|----------|---------|-------------|
| `INFERENCE_PROFILE_REGIONS` | `""` (all) | Comma-separated region prefixes to filter inference profiles (e.g. `au`, `au,us`) |

**Files:** `src/api/models/bedrock.py`, `src/api/setting.py`
**Commits:** `c381c20`

---

### 8. Adaptive Thinking Auto-Detection

Newer Claude generations (Opus 4.7+, Sonnet 5+) reject the legacy `reasoning_config={type:enabled, budget_tokens:N}` scheme and require `thinking={type:adaptive}` + `output_config={effort:...}` instead. Rather than hardcoding model IDs (which go stale with each new release), this detects Bedrock's own validation error message and retries once with the new scheme.

**Key changes:**
- Auto-detect adaptive thinking models via Bedrock's validation error on first request
- Runtime cache (`ADAPTIVE_THINKING_MODELS`) ensures only the first request per model per process restart pays the retry cost
- Adds `display:summarized` to adaptive thinking requests (required to get non-empty reasoning text back from Bedrock)
- Maps OpenAI `reasoning_effort` to Bedrock `effort` parameter for adaptive models

| Variable | Default | Description |
|----------|---------|-------------|
| `ADAPTIVE_THINKING_MODELS` | `""` | Comma-separated model IDs to pre-seed the adaptive thinking cache (skip first-request retry) |

**Files:** `src/api/models/bedrock.py`
**Commits:** `5c4cfc3`

---

### 9. Upstream Sync (Oct 2026)

Merged 12 upstream commits including security fixes, dependency bumps, and the deprecation notice.

**Key upstream changes merged:**
- SSRF validation for image URLs (`#262`)
- Starlette bump to 1.3.1, requests bump to 2.33.0
- Docker base image CVE fixes (`#244`)
- `max_tokens` default handling improvement (`#241`)
- Claude Sonnet 4.6 temperature/top-p conflict handling (`#238`)
- ImageContent schema fix (`#234`)
- `additionalModelRequestFields` merge fix
- Deprecation notice pointing to native Bedrock APIs (`#264`)

**Commits:** `637cde2`

---

## All Fork-Specific Commits

Listed newest-first. Excludes commits that exist in `upstream/main`.

| Commit | Description | Feature |
|--------|-------------|---------|
| `637cde2` | merge: upstream/main (12 commits) | Upstream sync |
| `5c4cfc3` | fix: auto-detect and retry with adaptive thinking | Adaptive thinking |
| `76caaf6` | fix: tool call streaming — correct index mapping + empty-arg handling | Tool call fix |
| `d4b9d45` | fix: tool call streaming — negative index and empty arguments | Tool call fix |
| `570522a` | fix: prevent event loop starvation during streaming and model listing | Event loop fix |
| `c381c20` | feat: region-filtered inference profiles + inference-profile-only support | Region filtering |
| `082fc63` | Diagnostics to investigate issue | Debugging (temporary) |
| `f85946d` | Update README: drop PR0, reflect final implementation state | Docs |
| `d5ddf86` | Centralise TRACE_LEVEL in setting.py | Logging refinement |
| `e7eb4df` | Simplify TRACE/DEBUG level config; conditional log format for ECS | Logging refinement |
| `3915501` | Remove RooCode reference from max_completion_tokens comment | Cleanup |
| `b094571` | Remove unused json import, use lazy %s formatting | Logging refinement |
| `97a74d9` | Nest profile resolution debug log inside isEnabledFor guard | Logging refinement |
| `cadbb63` | Simplify validation error handler logging | Logging refinement |
| `e108671` | Guard debug log calls with isEnabledFor | Logging refinement |
| `bacbb2c` | fix: drop custom log format for CloudWatch consistency | Logging refinement |
| `ac891b4` | Merge PR3: logging overhaul | PR 226 |
| `484f670` | Merge PR2: configurable max_tokens | PR 228 |
| `d30b7c8` | Merge PR1: prompt caching schema | PR 230 |
| `91f9a49` | Merge PR0: enhanced validation errors | Validation errors |
| `0c54745` | docs: add fork README documenting my contributions | Docs |
| `26c68c3` | Add per-request USAGE logging, three-tier log levels | PR 226 |
| `14fd3bd` | feat: make default max_tokens configurable | PR 228 |
| `1d95046` | feat: add prompt caching schema support | PR 230 |
| `e8f19e3` | fix: enhance validation error handler | Validation errors |

---

## Environment Variables (All Fork Additions)

| Variable | Default | Description |
|----------|---------|-------------|
| `DEFAULT_MAX_TOKENS` | `2048` | Default max tokens when not specified in request |
| `TRACE` | `false` | Enable TRACE-level logging below DEBUG |
| `USAGE_USER_HEADER` | `""` | HTTP header for user identity in USAGE logs |
| `USAGE_CHAT_ID_HEADER` | `""` | HTTP header for chat/session ID in USAGE logs |
| `INFERENCE_PROFILE_REGIONS` | `""` (all) | Comma-separated region prefixes to filter inference profiles |
| `ADAPTIVE_THINKING_MODELS` | `""` | Comma-separated model IDs to pre-seed adaptive thinking cache |

---

## Setup

To use this fork with all enhancements merged:

```bash
git clone https://github.com/bluecrystalsolutions/bedrock-access-gateway.git
cd bedrock-access-gateway
git checkout my-contributions
```

Or to use a specific feature branch:

```bash
git checkout feature/logging-overhaul       # PR 226
git checkout feature/configurable-max-tokens # PR 228
git checkout feature/prompt-caching-schema   # PR 230
```

## Merge Compatibility

All 3 upstream PRs are independent branches off `main` and merge cleanly together. The directly-committed fixes (tool call streaming, event loop, inference profiles, adaptive thinking) build on top of the merged PRs.

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
