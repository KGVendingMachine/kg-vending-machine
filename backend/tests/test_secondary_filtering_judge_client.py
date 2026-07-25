"""
tests/test_secondary_filtering_judge_client.py

app/ai/secondary_filtering_judge_client.py 테스트. 실제 OpenAI API는 호출하지
않고, client.chat.completions.create를 가짜로 대체해서 재시도/파싱 실패
처리 로직만 검증한다(tests/test_ai_normalizer.py와 동일한 접근).
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from openai import AuthenticationError, RateLimitError

from app.ai.secondary_filtering_judge_client import AiJudgeError, judge_criteria

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


def _valid_judgment_json() -> str:
    return (
        '{"judgments": ['
        '{"criterion_id": "elig:region", "status": "충족", "evidence": "서울 소재"},'
        '{"criterion_id": "excl:target:0", "status": "미충족", "evidence": "휴업 중"}'
        "]}"
    )


async def test_judge_criteria_returns_empty_dict_without_calling_api_when_no_criteria():
    client = _fake_client([])

    result = await judge_criteria(
        company_profile_text="기업 정보", criteria=[], evidence_texts=[], client=client
    )

    assert result == {}
    assert client.chat.completions.create.call_count == 0


async def test_judge_criteria_returns_status_and_evidence_on_success():
    client = _fake_client([_fake_response(_valid_judgment_json())])

    result = await judge_criteria(
        company_profile_text="기업 정보",
        criteria=[("elig:region", "지역 요건"), ("excl:target:0", "제외 대상 요건")],
        evidence_texts=["공고문 발췌"],
        client=client,
    )

    assert result["elig:region"] == ("충족", "서울 소재")
    assert result["excl:target:0"] == ("미충족", "휴업 중")
    assert client.chat.completions.create.call_count == 1


async def test_judge_criteria_coerces_string_null_evidence_to_none():
    # LLM이 프롬프트 지시를 무시하고 evidence 없음을 JSON null 대신 문자열
    # "null"로 출력하는 경우가 실측으로 확인됨(2026-07-15, 화면에 "— null"이
    # 그대로 노출됨) — None으로 정규화돼야 프론트가 조건부 렌더링을 건너뛴다.
    string_null_json = (
        '{"judgments": [{"criterion_id": "elig:size", "status": "정보부족", '
        '"evidence": "null"}]}'
    )
    client = _fake_client([_fake_response(string_null_json)])

    result = await judge_criteria(
        company_profile_text="기업 정보",
        criteria=[("elig:size", "기업 규모 요건")],
        evidence_texts=[],
        client=client,
    )

    assert result["elig:size"] == ("정보부족", None)


async def test_judge_criteria_normalizes_unknown_status_to_information_lacking():
    unknown_status_json = '{"judgments": [{"criterion_id": "elig:region", "status": "모름", "evidence": null}]}'
    client = _fake_client([_fake_response(unknown_status_json)])

    result = await judge_criteria(
        company_profile_text="기업 정보",
        criteria=[("elig:region", "지역 요건")],
        evidence_texts=[],
        client=client,
    )

    assert result["elig:region"] == ("정보부족", None)


async def test_judge_criteria_retries_after_retryable_api_error():
    client = _fake_client([_rate_limit_error(), _fake_response(_valid_judgment_json())])

    result = await judge_criteria(
        company_profile_text="기업 정보",
        criteria=[("elig:region", "지역 요건")],
        evidence_texts=[],
        client=client,
    )

    assert result["elig:region"] == ("충족", "서울 소재")
    assert client.chat.completions.create.call_count == 2


async def test_judge_criteria_retries_after_malformed_json():
    client = _fake_client(
        [_fake_response("이건 JSON이 아님"), _fake_response(_valid_judgment_json())]
    )

    result = await judge_criteria(
        company_profile_text="기업 정보",
        criteria=[("elig:region", "지역 요건")],
        evidence_texts=[],
        client=client,
    )

    assert result["elig:region"] == ("충족", "서울 소재")
    assert client.chat.completions.create.call_count == 2


async def test_judge_criteria_raises_after_exhausting_retries():
    client = _fake_client(
        [_rate_limit_error(), _rate_limit_error(), _rate_limit_error()]
    )

    with pytest.raises(AiJudgeError) as exc_info:
        await judge_criteria(
            company_profile_text="기업 정보",
            criteria=[("elig:region", "지역 요건")],
            evidence_texts=[],
            client=client,
        )

    assert isinstance(exc_info.value.__cause__, RateLimitError)
    assert client.chat.completions.create.call_count == 3


async def test_judge_criteria_fails_fast_on_non_retryable_error():
    client = _fake_client([_auth_error()])

    with pytest.raises(AiJudgeError) as exc_info:
        await judge_criteria(
            company_profile_text="기업 정보",
            criteria=[("elig:region", "지역 요건")],
            evidence_texts=[],
            client=client,
        )

    assert isinstance(exc_info.value.__cause__, AuthenticationError)
    assert client.chat.completions.create.call_count == 1
