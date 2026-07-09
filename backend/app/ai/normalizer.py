"""
ai/normalizer.py

NRM-001: LLM(OpenAI) 호출 + 재시도를 담당.
services/business_plan_service.py가 기대하는 NormalizeFn 시그니처
(Callable[[str], Awaitable[NormalizedBusinessPlanSchema]])의 실제 구현.
"""

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

from app.ai.prompts import SYSTEM_PROMPT, build_user_prompt
from app.core.config import get_settings
from app.schemas.business_plan import NormalizedBusinessPlanSchema

logger = logging.getLogger(__name__)

# 일시적인 문제라 재시도하면 나아질 수 있는 에러들. 인증/요청형식 오류 등은 재시도해도
# 똑같이 실패하므로 여기 넣지 않고 즉시 AiNormalizationError로 감싸서 올린다.
_RETRYABLE_ERRORS = (
    RateLimitError,
    APITimeoutError,
    APIConnectionError,
    InternalServerError,
)


class AiNormalizationError(Exception):
    """LLM 정규화가 (재시도 끝에도) 실패했을 때. 원인은 __cause__로 확인."""


def _build_client() -> AsyncOpenAI:
    settings = get_settings()
    return AsyncOpenAI(
        api_key=settings.OPENAI_API_KEY, timeout=settings.OPENAI_TIMEOUT_SECONDS
    )


async def normalize_text(
    raw_text: str, *, client: AsyncOpenAI | None = None
) -> NormalizedBusinessPlanSchema:
    """
    raw_text를 LLM에 보내 NormalizedBusinessPlanSchema로 정규화.

    OpenAI Structured Outputs(strict 모드)는 스키마의 모든 object에
    additionalProperties=false를 강제해서, 카테고리별 자유 확장용 "extra: dict"
    필드와 맞지 않는다. 그래서 JSON 모드로 호출하고 pydantic으로 직접 검증하며,
    API 에러/파싱 실패 모두 OPENAI_MAX_RETRIES까지 재시도한다.
    """
    settings = get_settings()
    active_client = client or _build_client()

    last_error: Exception | None = None
    for attempt in range(1, settings.OPENAI_MAX_RETRIES + 1):
        try:
            response = await active_client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": build_user_prompt(raw_text)},
                ],
            )
        except _RETRYABLE_ERRORS as exc:
            last_error = exc
            logger.warning(
                "OpenAI 호출 실패 (attempt %s/%s): %s",
                attempt,
                settings.OPENAI_MAX_RETRIES,
                exc,
            )
            continue
        except OpenAIError as exc:
            raise AiNormalizationError("OpenAI 호출에 실패했습니다.") from exc

        content = response.choices[0].message.content or ""
        try:
            return NormalizedBusinessPlanSchema.model_validate_json(content)
        except ValidationError as exc:
            last_error = exc
            logger.warning(
                "LLM 응답 파싱 실패 (attempt %s/%s): %s",
                attempt,
                settings.OPENAI_MAX_RETRIES,
                exc,
            )
            continue

    raise AiNormalizationError(
        f"정규화 {settings.OPENAI_MAX_RETRIES}회 재시도 후 실패"
    ) from last_error
