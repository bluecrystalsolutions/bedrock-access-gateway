"""Unit tests for cachePoint model gating.

Tests that non-caching models (Qwen, DeepSeek, etc.) never get cachePoint
blocks, and that the runtime-learning set NO_CACHE_MODELS works correctly.
"""

from unittest.mock import patch

import pytest

from api.models.bedrock import BedrockModel, NO_CACHE_MODELS
from conftest import (
    CLAUDE_MODEL,
    DEEPSEEK_MODEL,
    QWEN_MODEL,
    count_cache_points,
    make_chat_request_with_markers,
)

# Models that should/shouldn't get cachePoints
_CACHE_SUPPORTED = [(CLAUDE_MODEL, True)]
_CACHE_UNSUPPORTED = [(QWEN_MODEL, False), (DEEPSEEK_MODEL, False)]
_ALL_MODELS = _CACHE_SUPPORTED + _CACHE_UNSUPPORTED


# ---------------------------------------------------------------------------
# Model-gating: _parse_content_parts and _parse_system_prompts
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("model_id,expect_cache", _ALL_MODELS, ids=[m[0] for m in _ALL_MODELS])
class TestModelGating:
    """Verify cachePoint presence/absence based on model support."""

    def test_content_parts(
        self, bedrock_model: BedrockModel, model_id: str, expect_cache: bool,
    ) -> None:
        """_parse_content_parts produces cachePoint only for supported models."""
        req = make_chat_request_with_markers(model_id)
        user_msg = req.messages[1]  # UserMessage
        with patch("api.models.bedrock.ENABLE_PROMPT_CACHING", False):
            result = bedrock_model._parse_content_parts(user_msg, model_id)
        assert count_cache_points(result) == (1 if expect_cache else 0)
        # Text content should always be present
        assert any("text" in b for b in result)

    def test_system_prompts(
        self, bedrock_model: BedrockModel, model_id: str, expect_cache: bool,
    ) -> None:
        """_parse_system_prompts produces cachePoint only for supported models."""
        req = make_chat_request_with_markers(model_id)
        with patch("api.models.bedrock.ENABLE_PROMPT_CACHING", False):
            result = bedrock_model._parse_system_prompts(req)
        assert count_cache_points(result) == (1 if expect_cache else 0)
        assert any("text" in b for b in result)


# ---------------------------------------------------------------------------
# NO_CACHE_MODELS runtime learning
# ---------------------------------------------------------------------------

class TestNoCacheModelsLearning:
    """Verify that NO_CACHE_MODELS prevents caching after learning."""

    def test_learned_model_skips_cache(self, bedrock_model: BedrockModel) -> None:
        """After adding a model to NO_CACHE_MODELS, _supports_prompt_caching returns False."""
        assert bedrock_model._supports_prompt_caching(CLAUDE_MODEL) is True
        NO_CACHE_MODELS.add(CLAUDE_MODEL)
        try:
            assert bedrock_model._supports_prompt_caching(CLAUDE_MODEL) is False
        finally:
            NO_CACHE_MODELS.discard(CLAUDE_MODEL)

    def test_learned_model_no_cache_points_in_content(
        self, bedrock_model: BedrockModel,
    ) -> None:
        """Model in NO_CACHE_MODELS → no cachePoint in _parse_content_parts."""
        req = make_chat_request_with_markers(CLAUDE_MODEL)
        NO_CACHE_MODELS.add(CLAUDE_MODEL)
        try:
            with patch("api.models.bedrock.ENABLE_PROMPT_CACHING", False):
                result = bedrock_model._parse_content_parts(
                    req.messages[1], CLAUDE_MODEL,
                )
            assert count_cache_points(result) == 0
        finally:
            NO_CACHE_MODELS.discard(CLAUDE_MODEL)


# ---------------------------------------------------------------------------
# _strip_cache_points
# ---------------------------------------------------------------------------

_STRIP_CASES = [
    pytest.param(
        {"system": [{"text": "hi"}, {"cachePoint": {"type": "default"}}], "messages": []},
        {"system": 1, "msg0": None},
        id="system_only",
    ),
    pytest.param(
        {"messages": [{"role": "user", "content": [
            {"text": "hello"}, {"cachePoint": {"type": "default"}},
        ]}]},
        {"system": None, "msg0": 1},
        id="messages_only",
    ),
    pytest.param(
        {
            "system": [{"text": "sys"}, {"cachePoint": {"type": "default"}}],
            "messages": [{"role": "user", "content": [
                {"text": "usr"}, {"cachePoint": {"type": "default"}},
                {"toolUse": {"toolUseId": "1", "name": "f", "input": {}}},
            ]}],
        },
        {"system": 1, "msg0": 2},
        id="mixed_blocks",
    ),
    pytest.param(
        {"system": [{"text": "s"}], "messages": [{"role": "user", "content": [{"text": "u"}]}]},
        {"system": 1, "msg0": 1},
        id="no_cache_points_noop",
    ),
]


@pytest.mark.parametrize("args,expected_lens", _STRIP_CASES)
def test_strip_cache_points(
    bedrock_model: BedrockModel, args: dict, expected_lens: dict,
) -> None:
    """_strip_cache_points removes all cachePoint blocks, preserves others."""
    result = bedrock_model._strip_cache_points(args)
    if expected_lens.get("system") is not None:
        assert len(result["system"]) == expected_lens["system"]
        assert all("cachePoint" not in b for b in result["system"])
    if expected_lens.get("msg0") is not None:
        content = result["messages"][0]["content"]
        assert len(content) == expected_lens["msg0"]
        assert all("cachePoint" not in b for b in content)


# ---------------------------------------------------------------------------
# _is_cache_not_supported_error
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("msg,expected", [
    ("AccessDeniedException: request did not allow prompt caching", True),
    ("DID NOT ALLOW PROMPT CACHING", True),
    ("ValidationException: model does not support thinking", False),
    ("", False),
], ids=["real_error", "uppercase", "unrelated", "empty"])
def test_is_cache_not_supported_error(msg: str, expected: bool) -> None:
    assert BedrockModel._is_cache_not_supported_error(msg) is expected
