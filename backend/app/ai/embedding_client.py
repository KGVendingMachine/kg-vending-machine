"""
ai/embedding_client.py

2차 필터링(docs/matching-pipeline.md 4단계)에서 청크 텍스트를 벡터로 바꾸는
OpenAI Embeddings 호출 + 재시도. app/ai/normalizer.py의 AsyncOpenAI 클라이언트
구성·재시도 패턴을 그대로 재사용한다 — 정규화(LLM)와 임베딩 둘 다 같은
OpenAI 계정/네트워크 실패 모드(rate limit, timeout 등)를 겪으므로 재시도
대상 예외도 동일하다.
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

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_RETRYABLE_ERRORS = (
    RateLimitError,
    APITimeoutError,
    APIConnectionError,
    InternalServerError,
)


class AiEmbeddingError(Exception):
    """임베딩 호출이 (재시도 끝에도) 실패했을 때. 원인은 __cause__로 확인."""


def _build_client() -> AsyncOpenAI:
    settings = get_settings()
    return AsyncOpenAI(
        api_key=settings.OPENAI_API_KEY,
        timeout=settings.OPENAI_EMBEDDING_TIMEOUT_SECONDS,
    )


async def embed_texts(
    texts: list[str], *, client: AsyncOpenAI | None = None
) -> list[list[float]]:
    """texts를 순서를 보존한 임베딩 벡터 목록으로 변환한다.

    OpenAI embeddings API는 여러 입력을 한 번에 받아 하나의 응답으로 돌려주므로
    청크 개수만큼 호출을 반복하지 않는다. 응답의 data[].index로 입력 순서와
    매칭해, API가 순서를 보장하지 않는 경우에도 안전하게 정렬한다.
    """
    if not texts:
        return []

    settings = get_settings()
    active_client = client or _build_client()

    last_error: Exception | None = None
    for attempt in range(1, settings.OPENAI_EMBEDDING_MAX_RETRIES + 1):
        try:
            response = await active_client.embeddings.create(
                model=settings.OPENAI_EMBEDDING_MODEL, input=texts
            )
        except _RETRYABLE_ERRORS as exc:
            last_error = exc
            logger.warning(
                "OpenAI 임베딩 호출 실패 (attempt %s/%s): %s",
                attempt,
                settings.OPENAI_EMBEDDING_MAX_RETRIES,
                exc,
            )
            continue
        except OpenAIError as exc:
            raise AiEmbeddingError("OpenAI 임베딩 호출에 실패했습니다.") from exc

        ordered = sorted(response.data, key=lambda item: item.index)
        return [item.embedding for item in ordered]

    raise AiEmbeddingError(
        f"임베딩 {settings.OPENAI_EMBEDDING_MAX_RETRIES}회 재시도 후 실패"
    ) from last_error
