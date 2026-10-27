"""Unit tests for cachePoint deduplication fix.

Tests the 4-cell matrix:
  1. No client markers, ENABLE_PROMPT_CACHING=false → no cachePoints
  2. No client markers, ENABLE_PROMPT_CACHING=true  → server injects cachePoints
  3. Client markers,    ENABLE_PROMPT_CACHING=false → client cachePoints only
  4. Client markers,    ENABLE_PROMPT_CACHING=true  → client cachePoints only (no dups)
"""

import os
from unittest.mock import patch

import pytest

from api.schema import (
    CacheControl,
    ChatRequest,
    SystemMessage,
    TextContent,
    UserMessage,
)
from api.models.bedrock import BedrockModel


# A Claude model that supports prompt caching
_MODEL = "anthropic.claude-sonnet-4-20250514"


def _make_model() -> BedrockModel:
    """Construct a minimal BedrockModel for testing."""
    return BedrockModel()


def _count_cache_points(blocks: list[dict]) -> int:
    """Count cachePoint entries in a list of Bedrock content blocks."""
    return sum(1 for b in blocks if "cachePoint" in b)


def _count_cache_points_in_messages(messages: list[dict]) -> int:
    """Count total cachePoint entries across all messages' content."""
    total = 0
    for msg in messages:
        for block in msg.get("content", []):
            if "cachePoint" in block:
                total += 1
    return total


# ---------------------------------------------------------------------------
# Helper: build ChatRequest variants
# ---------------------------------------------------------------------------

def _chat_request_no_markers() -> ChatRequest:
    """ChatRequest with plain string content (no cache_control markers)."""
    return ChatRequest(
        model=_MODEL,
        messages=[
            SystemMessage(content="You are a helpful assistant. " * 50),
            UserMessage(content="Say hello"),
        ],
    )


def _chat_request_with_client_markers() -> ChatRequest:
    """ChatRequest with cache_control markers on content blocks (ZooCode-style)."""
    return ChatRequest(
        model=_MODEL,
        messages=[
            SystemMessage(
                content=[
                    TextContent(
                        text="You are a helpful assistant. " * 50,
                        cache_control=CacheControl(type="ephemeral"),
                    ),
                ],
            ),
            UserMessage(
                content=[
                    TextContent(
                        text="Say hello",
                        cache_control=CacheControl(type="ephemeral"),
                    ),
                ],
            ),
        ],
    )


# ---------------------------------------------------------------------------
# Test _request_has_client_cache_markers
# ---------------------------------------------------------------------------

class TestClientCacheMarkerDetection:
    """Tests for _request_has_client_cache_markers helper."""

    def test_no_markers_string_content(self) -> None:
        model = _make_model()
        req = _chat_request_no_markers()
        assert model._request_has_client_cache_markers(req) is False

    def test_markers_present(self) -> None:
        model = _make_model()
        req = _chat_request_with_client_markers()
        assert model._request_has_client_cache_markers(req) is True

    def test_list_content_without_cache_control(self) -> None:
        """List content blocks but no cache_control set."""
        model = _make_model()
        req = ChatRequest(
            model=_MODEL,
            messages=[
                SystemMessage(
                    content=[TextContent(text="plain system prompt")],
                ),
                UserMessage(content="hello"),
            ],
        )
        assert model._request_has_client_cache_markers(req) is False


# ---------------------------------------------------------------------------
# 4-cell matrix tests for _parse_system_prompts
# ---------------------------------------------------------------------------

class TestSystemPromptsCacheDedup:
    """Verify cachePoint counts in _parse_system_prompts output."""

    def test_no_markers_caching_disabled(self) -> None:
        """Cell 1: No client markers, ENABLE_PROMPT_CACHING=false → 0 cachePoints."""
        model = _make_model()
        req = _chat_request_no_markers()
        with patch("api.models.bedrock.ENABLE_PROMPT_CACHING", False):
            result = model._parse_system_prompts(req)
        assert _count_cache_points(result) == 0

    def test_no_markers_caching_enabled(self) -> None:
        """Cell 2: No client markers, ENABLE_PROMPT_CACHING=true → 1 cachePoint."""
        model = _make_model()
        req = _chat_request_no_markers()
        with patch("api.models.bedrock.ENABLE_PROMPT_CACHING", True):
            result = model._parse_system_prompts(req)
        assert _count_cache_points(result) == 1

    def test_client_markers_caching_disabled(self) -> None:
        """Cell 3: Client markers, ENABLE_PROMPT_CACHING=false → client cachePoints only."""
        model = _make_model()
        req = _chat_request_with_client_markers()
        with patch("api.models.bedrock.ENABLE_PROMPT_CACHING", False):
            result = model._parse_system_prompts(req)
        # Mechanism A produces 1 cachePoint from the system message's cache_control
        assert _count_cache_points(result) == 1

    def test_client_markers_caching_enabled(self) -> None:
        """Cell 4: Client markers, ENABLE_PROMPT_CACHING=true → still only 1 cachePoint (no dup)."""
        model = _make_model()
        req = _chat_request_with_client_markers()
        with patch("api.models.bedrock.ENABLE_PROMPT_CACHING", True):
            result = model._parse_system_prompts(req)
        # Fix: Mechanism B is skipped because client markers detected
        assert _count_cache_points(result) == 1


# ---------------------------------------------------------------------------
# 4-cell matrix tests for _parse_messages
# ---------------------------------------------------------------------------

class TestMessagesCacheDedup:
    """Verify cachePoint counts in _parse_messages output."""

    def test_no_markers_caching_disabled(self) -> None:
        """Cell 1: No client markers, ENABLE_PROMPT_CACHING=false → 0 cachePoints."""
        model = _make_model()
        req = _chat_request_no_markers()
        with patch("api.models.bedrock.ENABLE_PROMPT_CACHING", False):
            result = model._parse_messages(req)
        assert _count_cache_points_in_messages(result) == 0

    def test_no_markers_caching_enabled(self) -> None:
        """Cell 2: No client markers, ENABLE_PROMPT_CACHING=true → 1 cachePoint on last user msg."""
        model = _make_model()
        req = _chat_request_no_markers()
        with patch("api.models.bedrock.ENABLE_PROMPT_CACHING", True):
            result = model._parse_messages(req)
        assert _count_cache_points_in_messages(result) == 1

    def test_client_markers_caching_disabled(self) -> None:
        """Cell 3: Client markers, ENABLE_PROMPT_CACHING=false → client cachePoints only."""
        model = _make_model()
        req = _chat_request_with_client_markers()
        with patch("api.models.bedrock.ENABLE_PROMPT_CACHING", False):
            result = model._parse_messages(req)
        # Mechanism A in _parse_content_parts produces 1 cachePoint from user's cache_control
        assert _count_cache_points_in_messages(result) == 1

    def test_client_markers_caching_enabled(self) -> None:
        """Cell 4: Client markers, ENABLE_PROMPT_CACHING=true → still only 1 (no dup)."""
        model = _make_model()
        req = _chat_request_with_client_markers()
        with patch("api.models.bedrock.ENABLE_PROMPT_CACHING", True):
            result = model._parse_messages(req)
        # Fix: Mechanism B skipped, only Mechanism A's cachePoint present
        assert _count_cache_points_in_messages(result) == 1


# ---------------------------------------------------------------------------
# Extra body override should still work
# ---------------------------------------------------------------------------

class TestExtraBodyOverride:
    """extra_body.prompt_caching should work regardless of client markers."""

    def test_extra_body_enables_caching_no_markers(self) -> None:
        """extra_body.prompt_caching.system=True with no client markers → 1 cachePoint."""
        model = _make_model()
        req = ChatRequest(
            model=_MODEL,
            messages=[
                SystemMessage(content="You are a helpful assistant. " * 50),
                UserMessage(content="hello"),
            ],
            extra_body={"prompt_caching": {"system": True, "messages": True}},
        )
        with patch("api.models.bedrock.ENABLE_PROMPT_CACHING", False):
            sys_result = model._parse_system_prompts(req)
            msg_result = model._parse_messages(req)
        assert _count_cache_points(sys_result) == 1
        assert _count_cache_points_in_messages(msg_result) == 1

    def test_extra_body_disables_caching(self) -> None:
        """extra_body.prompt_caching.system=False with ENV=true → 0 cachePoints."""
        model = _make_model()
        req = ChatRequest(
            model=_MODEL,
            messages=[
                SystemMessage(content="You are a helpful assistant. " * 50),
                UserMessage(content="hello"),
            ],
            extra_body={"prompt_caching": {"system": False, "messages": False}},
        )
        with patch("api.models.bedrock.ENABLE_PROMPT_CACHING", True):
            sys_result = model._parse_system_prompts(req)
            msg_result = model._parse_messages(req)
        assert _count_cache_points(sys_result) == 0
        assert _count_cache_points_in_messages(msg_result) == 0
