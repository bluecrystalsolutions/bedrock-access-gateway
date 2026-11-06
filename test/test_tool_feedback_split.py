"""Unit test (opt-in workaround): split approve/deny-style feedback out of tool_result.

Some agentic coding clients implement an approve/deny workflow for tool calls
where free-text feedback typed alongside an approval or denial gets glued in
front of (or merged with) the tool's real output, all as the content of a
single `tool_result` block -- typically shaped like
`{"status":"approved"|"denied","feedback":"..."}` followed by the actual tool
output. Instructions buried this way inside tool output are easy for a model
to mistake for untrusted tool content and ignore, rather than treat as a
genuine user instruction.

A proposed BAG-side opt-in workaround, gated behind the
`BAG_SPLIT_TOOL_FEEDBACK` environment variable, would detect this exact JSON
prefix in `_extract_tool_content()` (bedrock.py:957) / `_parse_messages()`
(bedrock.py:930), strip it out of the `toolResult` content, and append it to
the same Bedrock user turn as a separate text block.

This test sets `BAG_SPLIT_TOOL_FEEDBACK=1` via `monkeypatch.setenv` and
asserts the CORRECT/expected behavior: the feedback text is split out of the
toolResult content and emitted as a separate text block in the same turn.
This currently FAILS because the feature does not exist yet -- BAG today
takes the whole merged blob as-is and forwards it as a single toolResult
content block, with no splitting logic at all.
"""

import json

from api.models.bedrock import BedrockModel
from api.schema import (
    AssistantMessage,
    ChatRequest,
    ResponseFunction,
    ToolCall,
    ToolMessage,
    UserMessage,
)
from conftest import CLAUDE_MODEL

FEEDBACK_TEXT = "Also create NOTES.md containing the word hello"
FAKE_LISTING = "README.md\npackage.json\nsrc/\nsrc/index.ts\nsrc/utils.ts"
TOOL_USE_ID = "tooluse_list1"


def _merged_feedback_chat_request() -> ChatRequest:
    """Approve/deny feedback JSON glued in front of real tool output, all as
    the content of ONE tool_result message."""
    merged = json.dumps({"status": "approved", "feedback": FEEDBACK_TEXT}) + "\n\n" + FAKE_LISTING
    return ChatRequest(
        model=CLAUDE_MODEL,
        messages=[
            UserMessage(content="Please list the files in the project root."),
            AssistantMessage(
                content=None,
                tool_calls=[
                    ToolCall(
                        id=TOOL_USE_ID,
                        function=ResponseFunction(
                            name="list_files", arguments=json.dumps({"path": "."})
                        ),
                    )
                ],
            ),
            ToolMessage(tool_call_id=TOOL_USE_ID, content=merged),
        ],
    )


def test_feedback_is_split_out_of_tool_result_when_gate_enabled(
    bedrock_model: BedrockModel, monkeypatch,
) -> None:
    monkeypatch.setenv("BAG_SPLIT_TOOL_FEEDBACK", "1")
    req = _merged_feedback_chat_request()

    messages = bedrock_model._parse_messages(req)

    tool_result_text = None
    feedback_block_found = False
    for msg in messages:
        for block in msg.get("content", []):
            if not isinstance(block, dict):
                continue
            if "toolResult" in block:
                tool_result_text = block["toolResult"]["content"][0]["text"]
            elif "text" in block and FEEDBACK_TEXT in block["text"]:
                feedback_block_found = True

    assert tool_result_text is not None, "no toolResult block found in parsed messages"
    assert FEEDBACK_TEXT not in tool_result_text, (
        "BAG_SPLIT_TOOL_FEEDBACK=1 is set but the approve/deny feedback text "
        "is still embedded inside the toolResult content -- the opt-in "
        "split-out behavior does not exist yet."
    )
    assert feedback_block_found, (
        "No separate text block containing the feedback text was found in "
        "the same Bedrock user turn -- BAG_SPLIT_TOOL_FEEDBACK is supposed "
        "to append it as a standalone text block."
    )
