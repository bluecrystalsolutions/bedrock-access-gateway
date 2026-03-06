import json
import logging
from typing import Annotated

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import StreamingResponse

from api.auth import api_key_auth
from api.models.bedrock import BedrockModel
from api.schema import ChatRequest, ChatResponse, ChatStreamResponse, Error
from api.setting import DEFAULT_MODEL, TRACE_LEVEL, USAGE_USER_HEADER, USAGE_CHAT_ID_HEADER

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/chat",
    dependencies=[Depends(api_key_auth)],
    # responses={404: {"description": "Not found"}},
)


@router.post(
    "/completions", response_model=ChatResponse | ChatStreamResponse | Error, response_model_exclude_unset=True
)
async def chat_completions(
    request: Request,
    chat_request: Annotated[
        ChatRequest,
        Body(
            examples=[
                {
                    "model": "anthropic.claude-3-sonnet-20240229-v1:0",
                    "messages": [
                        {"role": "system", "content": "You are a helpful assistant."},
                        {"role": "user", "content": "Hello!"},
                    ],
                }
            ],
        ),
    ],
):
    # DIAG: Log raw body size and compare raw vs parsed message counts
    try:
        raw_body = await request.body()
        raw_body_size = len(raw_body)
        raw_json = json.loads(raw_body)
        raw_msg_count = len(raw_json.get("messages", []))
        raw_msg_roles = [m.get("role", "?") for m in raw_json.get("messages", [])]
        parsed_msg_count = len(chat_request.messages)
        parsed_msg_roles = [m.role for m in chat_request.messages]
        logger.warning(
            "DIAG-BODY | body_size=%d | raw_messages=%d | parsed_messages=%d | raw_roles=%s | parsed_roles=%s",
            raw_body_size, raw_msg_count, parsed_msg_count,
            raw_msg_roles, parsed_msg_roles,
        )
        if raw_msg_count != parsed_msg_count:
            logger.error(
                "DIAG-MISMATCH | %d messages in raw body but %d after Pydantic parsing! Messages may have been dropped.",
                raw_msg_count, parsed_msg_count,
            )
            # Log details of each raw message to identify which ones were dropped
            for i, raw_msg in enumerate(raw_json.get("messages", [])):
                role = raw_msg.get("role", "?")
                content = raw_msg.get("content")
                content_type = type(content).__name__
                content_preview = ""
                if isinstance(content, str):
                    content_preview = content[:100]
                elif isinstance(content, list):
                    content_preview = str([{k: v for k, v in item.items() if k == "type"} if isinstance(item, dict) else type(item).__name__ for item in content[:5]])
                logger.error(
                    "DIAG-RAW-MSG[%d] | role=%s | content_type=%s | has_tool_calls=%s | preview=%s",
                    i, role, content_type, bool(raw_msg.get("tool_calls")), content_preview,
                )
    except Exception as e:
        logger.warning("DIAG-BODY failed: %s", str(e))

    if logger.isEnabledFor(TRACE_LEVEL):
        logger.log(
            TRACE_LEVEL,
            "Request headers: %s",
            json.dumps(dict(request.headers), indent=2),
        )
        logger.log(
            TRACE_LEVEL,
            "Incoming chat completion request (raw parsed body): %s",
            json.dumps(chat_request.model_dump(), indent=2, default=str),
        )
    if chat_request.model.lower().startswith("gpt-"):
        chat_request.model = DEFAULT_MODEL

    # Exception will be raised if model not supported.
    # Compute effective max_tokens (same logic as bedrock.py _parse_request)
    effective_max_tokens = (
        chat_request.max_completion_tokens
        if chat_request.max_completion_tokens is not None
        else chat_request.max_tokens
    )
    model = BedrockModel()
    model.request_meta = {
        "user_email": request.headers.get(USAGE_USER_HEADER, "-") if USAGE_USER_HEADER else "-",
        "chat_id": request.headers.get(USAGE_CHAT_ID_HEADER, "-") if USAGE_CHAT_ID_HEADER else "-",
        "max_tokens": effective_max_tokens,
        "user_agent": request.headers.get("user-agent", "-"),
    }
    model.validate(chat_request)
    if chat_request.stream:
        return StreamingResponse(content=model.chat_stream(chat_request), media_type="text/event-stream")
    return await model.chat(chat_request)
