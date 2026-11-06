"""Unit test: a Bedrock content-filter stop must not produce a silent empty reply.

Bedrock can return `messageStop.stopReason == "content_filtered"` together with
zero output tokens (Anthropic's content filter can fire on some first-person,
deliberative "reasoning-style" text, regardless of topic). `chat_stream()`
(bedrock.py:729) and `_create_response_stream()` (bedrock.py:1362) have no
branch that detects this shape and surfaces a visible message to the caller --
the stream simply ends with an empty-content finish_reason chunk. A calling
client then sees an empty assistant turn with no indication of *why*, which
can trigger retry logic that resubmits the same request (and, if the
conversation includes pending tool calls, can lead to duplicate tool-result
submissions on the retry).

This test asserts the CORRECT/expected behavior (some visible, human-readable
text is emitted for this shape) and therefore currently FAILS against the
unpatched source. `_convert_finish_reason()` (bedrock.py:1640) already maps
`content_filtered` -> `content_filter` correctly and is NOT under test here --
only the silent-empty-reply behavior of the stream loop is.

This only exercises the deterministic BAG-side reaction to a Bedrock response
that has *already* decided to filter -- it depends only on response shape,
not on what text caused Bedrock to filter it.
"""

import asyncio
import json
from unittest.mock import AsyncMock

from api.models.bedrock import BedrockModel
from api.schema import ChatRequest, UserMessage
from conftest import CLAUDE_MODEL


def _make_chat_request() -> ChatRequest:
    return ChatRequest(
        model=CLAUDE_MODEL,
        messages=[UserMessage(content="Say hello")],
        stream=True,
    )


def _content_filtered_zero_token_stream() -> list[dict]:
    """Synthetic Bedrock stream shape: filtered with zero output tokens."""
    return [
        {"messageStart": {"role": "assistant"}},
        {"messageStop": {"stopReason": "content_filtered"}},
        {"metadata": {"usage": {"totalTokens": 12, "outputTokens": 0}}},
    ]


def _collect_stream_text(raw_chunks: list[bytes]) -> str:
    """Concatenate all delta.content strings across SSE chunks."""
    text = ""
    for raw in raw_chunks:
        line = raw.decode().strip()
        assert line.startswith("data:")
        payload = line[len("data:"):].strip()
        if payload == "[DONE]":
            continue
        data = json.loads(payload)
        for choice in data.get("choices", []):
            delta = choice.get("delta", {})
            if delta.get("content"):
                text += delta["content"]
    return text


def test_content_filtered_zero_tokens_yields_visible_text(bedrock_model: BedrockModel) -> None:
    """A content_filtered + 0-output-token Bedrock stream must produce a
    visible message to the caller, not a silently empty assistant turn.
    """
    chat_request = _make_chat_request()
    bedrock_model._invoke_bedrock = AsyncMock(
        return_value={"stream": _content_filtered_zero_token_stream()}
    )

    async def _run() -> list[bytes]:
        return [chunk async for chunk in bedrock_model.chat_stream(chat_request)]

    raw_chunks = asyncio.run(_run())
    visible_text = _collect_stream_text(raw_chunks)

    # Today the stream produces finish_reason="content_filter" with an empty
    # delta.content on every chunk -- nothing visible is ever emitted. This
    # assertion encodes the desired fix: some non-empty, human-readable text
    # must be emitted for this shape (e.g. "[Blocked by provider content
    # filter]"), instead of silence.
    assert visible_text.strip() != "", (
        "chat_stream() produced no visible content for a content_filtered, "
        "zero-output-token stream -- a provider content-filter stop should "
        "surface a visible message instead of ending the stream silently."
    )
