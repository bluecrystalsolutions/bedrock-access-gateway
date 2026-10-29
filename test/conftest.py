import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

# api.auth refuses to import without an API key, and api.setting reads its
# defaults at import time, so both are set before any api module is imported.
os.environ.setdefault("API_KEY", "test-api-key")

import pytest

from api.models.bedrock import BedrockModel
from api.schema import CacheControl, ChatRequest, SystemMessage, TextContent, UserMessage


# ---------------------------------------------------------------------------
# Shared test fixtures and helpers for prompt-caching tests
# ---------------------------------------------------------------------------

# A Claude model that supports prompt caching
CLAUDE_MODEL = "anthropic.claude-sonnet-4-20250514"

# Models that do NOT support prompt caching
QWEN_MODEL = "qwen.qwen-2-5-72b-instruct-v1:0"
DEEPSEEK_MODEL = "deepseek.deepseek-r1-v1:0"


@pytest.fixture
def bedrock_model() -> BedrockModel:
    """Construct a minimal BedrockModel for testing."""
    return BedrockModel()


def count_cache_points(blocks: list[dict]) -> int:
    """Count cachePoint entries in a list of Bedrock content blocks."""
    return sum(1 for b in blocks if "cachePoint" in b)


def count_cache_points_in_messages(messages: list[dict]) -> int:
    """Count total cachePoint entries across all messages' content."""
    total = 0
    for msg in messages:
        for block in msg.get("content", []):
            if "cachePoint" in block:
                total += 1
    return total


def make_chat_request_no_markers(model: str = CLAUDE_MODEL) -> ChatRequest:
    """ChatRequest with plain string content (no cache_control markers)."""
    return ChatRequest(
        model=model,
        messages=[
            SystemMessage(content="You are a helpful assistant. " * 50),
            UserMessage(content="Say hello"),
        ],
    )


def make_chat_request_with_markers(model: str = CLAUDE_MODEL) -> ChatRequest:
    """ChatRequest with cache_control markers on content blocks (client-side markers)."""
    return ChatRequest(
        model=model,
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
