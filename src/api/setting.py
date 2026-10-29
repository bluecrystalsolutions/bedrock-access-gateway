import logging
import os

API_ROUTE_PREFIX = os.environ.get("API_ROUTE_PREFIX", "/api/v1")

TITLE = "Amazon Bedrock Proxy APIs"
SUMMARY = "OpenAI-Compatible RESTful APIs for Amazon Bedrock"
VERSION = "0.1.0"
DESCRIPTION = """
Use OpenAI-Compatible RESTful APIs for Amazon Bedrock models.
"""

DEBUG = os.environ.get("DEBUG", "false").lower() != "false"
TRACE = os.environ.get("TRACE", "false").lower() != "false"

# Custom log level below DEBUG(10) for per-chunk streaming logs.
# Registered once here so every module can import TRACE_LEVEL.
TRACE_LEVEL = 5
logging.addLevelName(TRACE_LEVEL, "TRACE")
AWS_REGION = os.environ.get("AWS_REGION", "us-west-2")
DEFAULT_MAX_TOKENS = int(os.environ.get("DEFAULT_MAX_TOKENS", "2048"))
DEFAULT_MODEL = os.environ.get("DEFAULT_MODEL", "anthropic.claude-3-sonnet-20240229-v1:0")
DEFAULT_EMBEDDING_MODEL = os.environ.get("DEFAULT_EMBEDDING_MODEL", "cohere.embed-multilingual-v3")
ENABLE_CROSS_REGION_INFERENCE = os.environ.get("ENABLE_CROSS_REGION_INFERENCE", "true").lower() != "false"
ENABLE_APPLICATION_INFERENCE_PROFILES = os.environ.get("ENABLE_APPLICATION_INFERENCE_PROFILES", "true").lower() != "false"
ENABLE_PROMPT_CACHING = os.environ.get("ENABLE_PROMPT_CACHING", "false").lower() != "false"

# Comma-separated list of region prefixes to include for SYSTEM_DEFINED inference
# profiles.  When set, only profiles whose ID starts with one of these prefixes
# are listed (e.g. "au" → only au.*, "au,us" → au.* and us.*).
# Empty string (default) means include ALL regions.
# Profiles are always fetched for feature detection; this only controls visibility.
_raw_regions = os.environ.get("INFERENCE_PROFILE_REGIONS", "").strip()
INFERENCE_PROFILE_REGIONS: list[str] = (
    [r.strip().rstrip(".") for r in _raw_regions.split(",") if r.strip()]
    if _raw_regions else []
)

# HTTP headers to extract for USAGE logging (configurable for different frontends).
# Leave unset to omit user/chat from USAGE lines. Set to the header names your
# upstream proxy sends; for OpenWebUI (ENABLE_FORWARD_USER_INFO_HEADERS):
# USAGE_USER_HEADER=x-openwebui-user-email, USAGE_CHAT_ID_HEADER=x-openwebui-chat-id
USAGE_USER_HEADER = os.environ.get("USAGE_USER_HEADER", "")
USAGE_CHAT_ID_HEADER = os.environ.get("USAGE_CHAT_ID_HEADER", "")

# Multimodal image inputs may reference a remote URL that the gateway fetches on
# behalf of the caller. See api/image_url.py for the checks applied to that URL.
ENABLE_IMAGE_URL_FETCH = os.environ.get("ENABLE_IMAGE_URL_FETCH", "true").lower() != "false"
# Optional comma-separated allowlist of hosts an image url may point at.
# Empty means any host that resolves to a globally routable address is allowed.
IMAGE_URL_ALLOWED_HOSTS = frozenset(
    host.strip().lower() for host in os.environ.get("IMAGE_URL_ALLOWED_HOSTS", "").split(",") if host.strip()
)
IMAGE_URL_MAX_SIZE_MB = int(os.environ.get("IMAGE_URL_MAX_SIZE_MB", "10"))
