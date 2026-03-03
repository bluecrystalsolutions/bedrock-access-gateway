# Bedrock Access Gateway — My Contributions

> Fork of [aws-samples/bedrock-access-gateway](https://github.com/aws-samples/bedrock-access-gateway) with enhancements for production logging, prompt caching, and operational visibility.

## Upstream

This is a fork of the [Bedrock Access Gateway](https://github.com/aws-samples/bedrock-access-gateway) project by AWS Samples. The upstream project provides an OpenAI-compatible API proxy for Amazon Bedrock, enabling drop-in replacement for applications built against the OpenAI SDK.

## My Contributions

The following pull requests have been submitted upstream. Each branch is independent and can be reviewed/merged separately.

### PR 1 — Prompt Caching Schema Support

| | |
|---|---|
| **Branch** | [`feature/prompt-caching-schema`](../../tree/feature/prompt-caching-schema) |
| **Status** | 🟢 [PR 230](https://github.com/aws-samples/bedrock-access-gateway/pull/230) |

Adds support for [Anthropic-style prompt caching](https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching) through the OpenAI-compatible API. Clients can now send structured system/developer messages with `cache_control` markers, which are translated to Bedrock's `cachePoint` blocks.

**Changes:**
- `CacheControl` model and `cache_control` field on `TextContent`
- `SystemMessage.content` and `DeveloperMessage.content` accept `str | list[TextContent]`
- `_parse_system_prompts` handles list-format content with cache markers
- `_parse_content_parts` emits `cachePoint` blocks

**Files:** `src/api/schema.py`, `src/api/models/bedrock.py`

---

### PR 2 — Configurable DEFAULT_MAX_TOKENS

| | |
|---|---|
| **Branch** | [`feature/configurable-max-tokens`](../../tree/feature/configurable-max-tokens) |
| **Status** | 🟢 [PR 228](https://github.com/aws-samples/bedrock-access-gateway/pull/228) |

Makes the default `max_tokens` value configurable via the `DEFAULT_MAX_TOKENS` environment variable (default: 2048, preserving existing behaviour). Also introduces `effective_max_tokens` which prefers `max_completion_tokens` over `max_tokens`, eliminating duplicate logic in the request parser.

**New environment variable:**

| Variable | Default | Description |
|----------|---------|-------------|
| `DEFAULT_MAX_TOKENS` | `2048` | Default max tokens when not specified in the request |

**Files:** `src/api/setting.py`, `src/api/schema.py`, `src/api/models/bedrock.py`

---

### PR 3 — Logging Overhaul: Three-tier Levels + USAGE Logging

| | |
|---|---|
| **Branch** | [`feature/logging-overhaul`](../../tree/feature/logging-overhaul) |
| **Status** | 🟢 [PR 226](https://github.com/aws-samples/bedrock-access-gateway/pull/226) |

Comprehensive logging improvement that replaces the binary `if DEBUG: logger.info()` pattern with a three-tier system (INFO → DEBUG → TRACE) and adds per-request USAGE logging at INFO level.

**Key changes:**
- Custom TRACE level (5) below DEBUG (10) for per-chunk streaming logs, centralised in `setting.py` and imported everywhere
- All `if DEBUG: logger.info` patterns converted to `logger.debug` or TRACE with lazy `%s` formatting
- Expensive debug operations guarded with `isEnabledFor` checks
- ECS/Fargate-aware log format — omits timestamps and brackets when `ECS_CONTAINER_METADATA_URI` is set (CloudWatch adds its own)
- INFO-level USAGE log line per request: user, chat, model, tokens in/out/cache, user-agent
- Configurable header extraction for user/chat attribution (proxy-agnostic)
- Improved validation error handler with error count at WARNING and rejected body at TRACE
- Only `api` logger hierarchy gets DEBUG/TRACE — boto3/botocore/urllib3 stay at INFO

**New environment variables:**

| Variable | Default | Description |
|----------|---------|-------------|
| `TRACE` | `false` | Enable TRACE-level logging (below DEBUG) for per-chunk streaming details |
| `USAGE_USER_HEADER` | `""` | HTTP header name to extract user identity for USAGE logging (e.g. `x-openwebui-user-email`) |
| `USAGE_CHAT_ID_HEADER` | `""` | HTTP header name to extract chat/session ID for USAGE logging (e.g. `x-openwebui-chat-id`) |

**USAGE log example:**
```
USAGE | user=admin@example.com | chat=abc-123 | model=anthropic.claude-sonnet-4-20250514-v1:0 | max_tokens=4096 | in=1523 | out=847 | cache_write=0 | cache_read=1200 | ua=OpenAI/Python 1.x
```

**Files:** `src/api/setting.py`, `src/api/app.py`, `src/api/routers/chat.py`, `src/api/models/bedrock.py`

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
git checkout feature/logging-overhaul
```

## Merge Compatibility

All 3 PRs are independent branches off `main` and have been verified to merge cleanly together. There are no conflicts between the branches.

## License

Same as upstream — see [LICENSE](LICENSE).
