"""Unit tests for cachePoint deduplication.

Tests the 4-cell matrix of (client_markers × ENABLE_PROMPT_CACHING) for both
_parse_system_prompts and _parse_messages, plus extra_body override.
"""

from unittest.mock import patch

import pytest

from api.schema import ChatRequest, SystemMessage, TextContent, UserMessage
from api.models.bedrock import BedrockModel
from conftest import (
    CLAUDE_MODEL,
    count_cache_points,
    count_cache_points_in_messages,
    make_chat_request_no_markers,
    make_chat_request_with_markers,
)


# ---------------------------------------------------------------------------
# Test _request_has_client_cache_markers
# ---------------------------------------------------------------------------

class TestClientCacheMarkerDetection:
    """Tests for _request_has_client_cache_markers helper."""

    @pytest.mark.parametrize("req_factory,expected", [
        (make_chat_request_no_markers, False),
        (make_chat_request_with_markers, True),
    ], ids=["no_markers", "with_markers"])
    def test_detection(
        self, bedrock_model: BedrockModel, req_factory, expected: bool,
    ) -> None:
        assert bedrock_model._request_has_client_cache_markers(req_factory()) is expected

    def test_list_content_without_cache_control(self, bedrock_model: BedrockModel) -> None:
        """List content blocks but no cache_control set."""
        req = ChatRequest(
            model=CLAUDE_MODEL,
            messages=[
                SystemMessage(content=[TextContent(text="plain system prompt")]),
                UserMessage(content="hello"),
            ],
        )
        assert bedrock_model._request_has_client_cache_markers(req) is False


# ---------------------------------------------------------------------------
# 4-cell matrix: (markers × caching_env) for system prompts and messages
# ---------------------------------------------------------------------------

_DEDUP_MATRIX = [
    # (has_markers, env_caching, expected_system_cp, expected_msg_cp, id)
    (False, False, 0, 0, "no_markers-env_off"),
    (False, True,  1, 1, "no_markers-env_on"),
    (True,  False, 1, 1, "with_markers-env_off"),
    (True,  True,  1, 1, "with_markers-env_on"),
]


@pytest.mark.parametrize(
    "has_markers,env_caching,expected_sys,expected_msg,label",
    _DEDUP_MATRIX,
    ids=[t[4] for t in _DEDUP_MATRIX],
)
class TestCacheDedupMatrix:
    """4-cell dedup matrix for both _parse_system_prompts and _parse_messages."""

    def test_system_prompts(
        self, bedrock_model: BedrockModel,
        has_markers: bool, env_caching: bool, expected_sys: int,
        expected_msg: int, label: str,
    ) -> None:
        req = make_chat_request_with_markers() if has_markers else make_chat_request_no_markers()
        with patch("api.models.bedrock.ENABLE_PROMPT_CACHING", env_caching):
            result = bedrock_model._parse_system_prompts(req)
        assert count_cache_points(result) == expected_sys

    def test_messages(
        self, bedrock_model: BedrockModel,
        has_markers: bool, env_caching: bool, expected_sys: int,
        expected_msg: int, label: str,
    ) -> None:
        req = make_chat_request_with_markers() if has_markers else make_chat_request_no_markers()
        with patch("api.models.bedrock.ENABLE_PROMPT_CACHING", env_caching):
            result = bedrock_model._parse_messages(req)
        assert count_cache_points_in_messages(result) == expected_msg


# ---------------------------------------------------------------------------
# Extra body override should still work
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("enable,expected_cp", [
    (True, 1),
    (False, 0),
], ids=["extra_body_enables", "extra_body_disables"])
class TestExtraBodyOverride:
    """extra_body.prompt_caching should override ENV setting."""

    def test_system_and_messages(
        self, bedrock_model: BedrockModel, enable: bool, expected_cp: int,
    ) -> None:
        req = ChatRequest(
            model=CLAUDE_MODEL,
            messages=[
                SystemMessage(content="You are a helpful assistant. " * 50),
                UserMessage(content="hello"),
            ],
            extra_body={"prompt_caching": {"system": enable, "messages": enable}},
        )
        # Invert ENV vs extra_body to prove extra_body wins
        with patch("api.models.bedrock.ENABLE_PROMPT_CACHING", not enable):
            sys_result = bedrock_model._parse_system_prompts(req)
            msg_result = bedrock_model._parse_messages(req)
        assert count_cache_points(sys_result) == expected_cp
        assert count_cache_points_in_messages(msg_result) == expected_cp
