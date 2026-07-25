import logging

from openai import (
    APIConnectionError,
    APITimeoutError,
    AsyncOpenAI,
    InternalServerError,
    OpenAIError,
    RateLimitError,
)
from pydantic import ValidationError

from app.ai.normalizer import AiNormalizationError
from app.ai.notice_prompts import NOTICE_SYSTEM_PROMPT, build_notice_user_prompt
from app.core.config import get_settings
from app.schemas.notice_normalization import NormalizedNoticeSchema

logger = logging.getLogger(__name__)

_RETRYABLE_ERRORS = (
    RateLimitError,
    APITimeoutError,
    APIConnectionError,
    InternalServerError,
)


def _build_client() -> AsyncOpenAI:
    settings = get_settings()
    return AsyncOpenAI(
        api_key=settings.OPENAI_API_KEY, timeout=settings.OPENAI_TIMEOUT_SECONDS
    )


async def normalize_notice_text(
    raw_text: str, *, client: AsyncOpenAI | None = None
) -> NormalizedNoticeSchema:
    settings = get_settings()
    active_client = client or _build_client()

    last_error: Exception | None = None
    for attempt in range(1, settings.OPENAI_MAX_RETRIES + 1):
        try:
            response = await active_client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": NOTICE_SYSTEM_PROMPT},
                    {"role": "user", "content": build_notice_user_prompt(raw_text)},
                ],
            )
        except _RETRYABLE_ERRORS as exc:
            last_error = exc
            logger.warning(
                "OpenAI notice normalization failed (attempt %s/%s): %s",
                attempt,
                settings.OPENAI_MAX_RETRIES,
                exc,
            )
            continue
        except OpenAIError as exc:
            raise AiNormalizationError("OpenAI notice normalization failed.") from exc

        content = response.choices[0].message.content or ""
        try:
            return NormalizedNoticeSchema.model_validate_json(content)
        except ValidationError as exc:
            last_error = exc
            logger.warning(
                "LLM notice response parsing failed (attempt %s/%s): %s",
                attempt,
                settings.OPENAI_MAX_RETRIES,
                exc,
            )
            continue

    raise AiNormalizationError(
        f"Notice normalization failed after {settings.OPENAI_MAX_RETRIES} attempts."
    ) from last_error
