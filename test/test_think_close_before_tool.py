"""Unit test: an open </think> tag must close before a tool call starts.

`_create_response_stream()` (bedrock.py:1362) closes an open `<think>` tag in
exactly two places: the plain-text delta branch (bedrock.py:1411-1418) and the
`signature` sub-field of a `reasoningContent` delta (bedrock.py:1427-1433),
plus a safety net at `messageStop` (bedrock.py:1473-1488). Critically, neither
of the `contentBlockStart`/`contentBlockDelta` branches for `toolUse`
(bedrock.py:1382-1407, bedrock.py:1434-1453) check or clear
`self.think_emitted`. So if a tool-use block starts immediately after a
reasoning block with no intervening signature delta, the close tag does not
fire until `messageStop` -- arriving as an orphaned fragment after all
tool-call argument deltas have already streamed.

This test builds a deterministic, hand-crafted chunk sequence (a reasoning
delta directly followed by a `contentBlockStart` tool-use block, with no
signature delta in between) and asserts the CORRECT/expected behavior: the
`<think>` tag must be closed at or before the tool-use start chunk. This
currently FAILS against the unpatched source.

Note: this specific sequencing (a tool-use block starting with literally no
intervening signature delta) has been investigated but not yet reproduced
against live Bedrock traffic -- Bedrock has so far always been observed to
send a signature delta first. This unit test proves the code-level gap
deterministically regardless of whether it has fired on live traffic yet.
"""

from api.models.bedrock import BedrockModel


def _reset_stream_state(model: BedrockModel) -> None:
    """Match the setup chat_stream() does at the start of each real request."""
    model.think_emitted = False
    model._tool_call_index_map = {}
    model._next_tool_index = 0
    model._tool_call_has_args = {}


def test_think_tag_closes_before_tool_use_starts(bedrock_model: BedrockModel) -> None:
    _reset_stream_state(bedrock_model)

    reasoning_chunk = {
        "contentBlockDelta": {
            "contentBlockIndex": 0,
            "delta": {"reasoningContent": {"text": "Let me think about the weather..."}},
        }
    }
    tool_start_chunk = {
        "contentBlockStart": {
            "contentBlockIndex": 1,
            "start": {"toolUse": {"toolUseId": "tool1", "name": "get_weather"}},
        }
    }

    reasoning_response = bedrock_model._create_response_stream(
        model_id="m", message_id="id1", chunk=reasoning_chunk
    )
    assert reasoning_response is not None
    assert bedrock_model.think_emitted is True  # reasoning block opened <think>

    tool_start_response = bedrock_model._create_response_stream(
        model_id="m", message_id="id1", chunk=tool_start_chunk
    )

    # Expected/fixed behavior: starting a tool_use block while a <think> tag
    # is open must close it first -- either by emitting "</think>" alongside
    # the tool_calls delta, or at minimum by resetting think_emitted before
    # the tool-use message is built. Today neither happens: the toolUse
    # branch never checks self.think_emitted, so the tag stays open
    # indefinitely (it will only close at messageStop, arriving as an
    # orphaned fragment after all tool-call argument deltas).
    assert bedrock_model.think_emitted is False, (
        "think_emitted is still True after a toolUse contentBlockStart "
        "chunk -- the </think> close tag was not emitted before the tool "
        "call started."
    )

    delta_content = ""
    if tool_start_response is not None and tool_start_response.choices:
        delta_content = tool_start_response.choices[0].delta.content or ""
    assert "</think>" in delta_content, (
        "The tool-use start chunk's delta.content does not contain "
        "'</think>' -- the reasoning block was never closed before the "
        "tool call began."
    )
