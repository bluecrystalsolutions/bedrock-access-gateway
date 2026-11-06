"""Unit tests: duplicate toolResult ids must not reach Bedrock (400 ValidationException).

`_reframe_multi_payloard()` (bedrock.py:1008) merges consecutive same-role
messages into one Bedrock turn, but never checks for repeated `toolUseId`
values inside `toolResult` blocks, and `_parse_messages()` (bedrock.py:862)
has no dedupe safety net either. A calling client's retry logic can submit
the same `tool_call_id`'s result multiple times in a row (e.g. after an
upstream empty-reply retry), which Bedrock then rejects with
`ValidationException: The toolResult blocks ... contain duplicate Ids` (400).

These tests assert the CORRECT/expected behavior (each toolUseId appears at
most once in the parsed Bedrock messages) and therefore currently FAIL
against the unpatched source. Scenario: a fully synthetic `get_time` tool
with a fake tool id, whose result is (accidentally) submitted twice.

Whatever causes a calling client to resubmit a duplicate tool_result lives in
that client's own retry logic and is out of scope for this gateway -- these
tests only check that BAG itself has no dedupe safety net before building the
Bedrock request.
"""

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

TOOL_USE_ID = "tooluse_dup1"


def _dup_tool_result_chat_request(extra_user_text: bool = False) -> ChatRequest:
    """Build a 'duplicate tool result x2 (client retry shape)' scenario."""
    messages = [
        UserMessage(content="What time is it?"),
        AssistantMessage(
            content=None,
            tool_calls=[
                ToolCall(
                    id=TOOL_USE_ID,
                    function=ResponseFunction(name="get_time", arguments="{}"),
                )
            ],
        ),
        ToolMessage(tool_call_id=TOOL_USE_ID, content="12:00"),
        ToolMessage(tool_call_id=TOOL_USE_ID, content="12:00"),
    ]
    if extra_user_text:
        messages.append(UserMessage(content="continue"))
    return ChatRequest(model=CLAUDE_MODEL, messages=messages)


def _count_tool_result_ids(messages: list[dict], tool_use_id: str) -> int:
    """Count toolResult blocks with a given toolUseId across all messages."""
    count = 0
    for msg in messages:
        for block in msg.get("content", []):
            if isinstance(block, dict) and "toolResult" in block:
                if block["toolResult"].get("toolUseId") == tool_use_id:
                    count += 1
    return count


def test_duplicate_tool_result_ids_are_deduped(bedrock_model: BedrockModel) -> None:
    """Sending the same tool_call_id's result twice must not produce two
    toolResult blocks for that id -- Bedrock rejects duplicate Ids with a
    400 ValidationException.
    """
    req = _dup_tool_result_chat_request()
    messages = bedrock_model._parse_messages(req)
    assert _count_tool_result_ids(messages, TOOL_USE_ID) == 1, (
        "_parse_messages() kept duplicate toolResult blocks for the same "
        "toolUseId -- Bedrock will reject this with 'ValidationException: "
        "The toolResult blocks ... contain duplicate Ids'."
    )


def test_duplicate_tool_result_ids_deduped_with_trailing_user_text(
    bedrock_model: BedrockModel,
) -> None:
    """Same as above, but with a trailing plain user-text message appended
    afterward -- the dedupe must still hold once the merge logic folds the
    trailing user text into the same Bedrock turn.
    """
    req = _dup_tool_result_chat_request(extra_user_text=True)
    messages = bedrock_model._parse_messages(req)
    assert _count_tool_result_ids(messages, TOOL_USE_ID) == 1, (
        "_parse_messages() kept duplicate toolResult blocks for the same "
        "toolUseId even with a trailing user-text message."
    )
