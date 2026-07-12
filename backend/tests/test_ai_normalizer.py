"""
tests/test_ai_normalizer.py

NRM-001: ai/normalizer.py 테스트.
실제 OpenAI API는 호출하지 않고, client.chat.completions.create를 가짜로 대체해서
재시도/파싱 실패 처리 로직만 검증한다.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from openai import AuthenticationError, RateLimitError

from app.ai.normalizer import AiNormalizationError, normalize_text
from app.schemas.business_plan import NormalizedBusinessPlanSchema, ProblemInfo

pytestmark = pytest.mark.anyio


def _fake_response(content: str) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


def _fake_client(side_effect: list) -> SimpleNamespace:
    create = AsyncMock(side_effect=side_effect)
    return SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )


def _rate_limit_error() -> RateLimitError:
    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    response = httpx.Response(429, request=request)
    return RateLimitError("rate limited", response=response, body=None)


def _auth_error() -> AuthenticationError:
    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    response = httpx.Response(401, request=request)
    return AuthenticationError("invalid api key", response=response, body=None)


def _valid_json() -> str:
    return NormalizedBusinessPlanSchema(
        problem=ProblemInfo(background="배경 설명")
    ).model_dump_json()


async def test_normalize_text_returns_schema_on_success():
    client = _fake_client([_fake_response(_valid_json())])

    result = await normalize_text("원문", client=client)

    assert result.problem.background == "배경 설명"
    assert client.chat.completions.create.call_count == 1


async def test_normalize_text_retries_after_retryable_api_error():
    client = _fake_client([_rate_limit_error(), _fake_response(_valid_json())])

    result = await normalize_text("원문", client=client)

    assert result.problem.background == "배경 설명"
    assert client.chat.completions.create.call_count == 2


async def test_normalize_text_retries_after_malformed_json():
    client = _fake_client(
        [_fake_response("이건 JSON이 아님"), _fake_response(_valid_json())]
    )

    result = await normalize_text("원문", client=client)

    assert result.problem.background == "배경 설명"
    assert client.chat.completions.create.call_count == 2


async def test_normalize_text_raises_after_exhausting_retries():
    client = _fake_client(
        [_rate_limit_error(), _rate_limit_error(), _rate_limit_error()]
    )

    with pytest.raises(AiNormalizationError) as exc_info:
        await normalize_text("원문", client=client)

    assert isinstance(exc_info.value.__cause__, RateLimitError)
    assert client.chat.completions.create.call_count == 3


async def test_normalize_text_fails_fast_on_non_retryable_error():
    client = _fake_client([_auth_error()])

    with pytest.raises(AiNormalizationError) as exc_info:
        await normalize_text("원문", client=client)

    assert isinstance(exc_info.value.__cause__, AuthenticationError)
    assert client.chat.completions.create.call_count == 1


def test_business_plan_schema_treats_null_extra_as_empty_dict():
    result = NormalizedBusinessPlanSchema.model_validate(
        {
            "company": {"extra": None},
            "problem": {"background": "배경", "extra": None},
            "solution": {
                "tech_stack": None,
                "differentiators": None,
                "extra": None,
            },
            "market": {"competitors": None, "extra": None},
            "funding": {"use_of_funds": None, "extra": None},
            "team": {"members": None, "extra": None},
        }
    )

    assert result.company.extra == {}
    assert result.problem.extra == {}
    assert result.solution.extra == {}
    assert result.solution.tech_stack == []
    assert result.solution.differentiators == []
    assert result.market.extra == {}
    assert result.market.competitors == []
    assert result.funding.extra == {}
    assert result.funding.use_of_funds == []
    assert result.team.extra == {}
    assert result.team.members == []
