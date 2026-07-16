"""
ai/secondary_filtering_judge_client.py

2차 필터링(docs/matching-pipeline.md 4단계, docs/secondary-filtering-llm-judge-guide.md
설계)의 LLM 판정 호출. app/ai/normalizer.py의 AsyncOpenAI 클라이언트 구성·재시도
패턴을 그대로 재사용한다 — JSON 모드(response_format={"type": "json_object"})를
쓰는 이유도 동일하다: 여기서 주고받는 판정 항목 수가 공고마다 달라 고정
스키마의 strict structured output과 맞지 않는다.

정규화(app/ai/normalizer.py)와 달리 여기서는 재시도를 다 써도 실패하면
"정보부족"으로 조용히 폴백하지 않고 AiJudgeError를 던진다 — 폴백 여부 자체를
호출자(secondary_filtering_judge_service)가 판정 실패 로그로 남기기 위함이다.
"""

import logging
from typing import Any

from openai import (
    APIConnectionError,
    APITimeoutError,
    AsyncOpenAI,
    InternalServerError,
    OpenAIError,
    RateLimitError,
)
from pydantic import BaseModel, ValidationError, field_validator

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_RETRYABLE_ERRORS = (
    RateLimitError,
    APITimeoutError,
    APIConnectionError,
    InternalServerError,
)

_VALID_STATUSES = {"충족", "미충족", "정보부족"}

_SYSTEM_PROMPT = """\
너는 정부지원사업 신청자격·적합도 판정 어시스턴트다. 주어진 기업 정보(사업계획서 \
요약, 기업 프로필)와 공고문 발췌를 근거로, 각 요건/평가기준 문장이 이 기업 기준으로 \
충족/미충족/정보부족 중 무엇인지 판단하라.

규칙:
- 근거(공고문 발췌·기업 정보)로 명확히 판단할 수 없으면 반드시 "정보부족"으로 \
표시하라. 추측하지 마라.
- "~에 해당하지 않음" 형태로 재구성된 제외요건 문장은, 기업이 실제로 그 \
제외 대상에 해당하면 "미충족"(제외 대상에 해당함), 해당하지 않으면 "충족"으로 \
판단하라.
- "다음 평가기준에 부합하는 근거가 있음" / "다음 우대조건에 해당함" 형태의 문장은 \
자격요건처럼 이분법적으로 있고 없고를 가르는 게 아니라 정성적 적합도 판단이다 — \
사업계획서 내용이 그 기준에 부합하는 구체적 근거가 있으면 "충족", 사업계획서 \
내용이 그 기준과 명백히 동떨어지면 "미충족", 부합 여부를 판단할 근거 자체가 \
부족하면 "정보부족"으로 표시하라.
- 각 판정에 근거가 된 문장을 evidence에 짧게 남겨라. 근거를 찾지 못했으면 evidence는
JSON null 값으로 두어라 — "null"이라는 글자를 따옴표로 감싼 문자열로 쓰지 마라.
- 아래 JSON 형식으로만 응답하라. 다른 텍스트는 포함하지 마라. 예시:
{"judgments": [
  {"criterion_id": "elig:region", "status": "충족", "evidence": "서울 소재 기업 대상"},
  {"criterion_id": "elig:size", "status": "정보부족", "evidence": null}
]}
"""


class AiJudgeError(Exception):
    """LLM 판정 호출이 (재시도 끝에도) 실패했을 때. 원인은 __cause__로 확인."""


def _coerce_null_string_to_none(value: Any) -> Any:
    """LLM이 프롬프트 지시를 무시하고 evidence 없음을 JSON null 대신
    문자열 "null"로 출력하는 경우가 실측으로 확인됨(2026-07-15, 화면에
    "— null"이 그대로 노출됨) — 프롬프트를 고쳐도 완전히 막을 보장이 없어
    스키마에서 방어적으로 한 번 더 걸러낸다."""
    if isinstance(value, str) and value.strip().lower() == "null":
        return None
    return value


class _JudgedCriterionResponse(BaseModel):
    criterion_id: str
    status: str
    evidence: str | None = None

    _coerce_evidence = field_validator("evidence", mode="before")(
        _coerce_null_string_to_none
    )


class _JudgeResponse(BaseModel):
    judgments: list[_JudgedCriterionResponse]


def _build_client() -> AsyncOpenAI:
    settings = get_settings()
    return AsyncOpenAI(
        api_key=settings.OPENAI_API_KEY, timeout=settings.OPENAI_TIMEOUT_SECONDS
    )


def _build_user_prompt(
    *,
    company_profile_text: str,
    criteria: list[tuple[str, str]],
    evidence_texts: list[str],
) -> str:
    criteria_block = "\n".join(f"- [{cid}] {statement}" for cid, statement in criteria)
    evidence_block = (
        "\n\n".join(evidence_texts) if evidence_texts else "(근거 발췌 없음)"
    )

    result = (
        f"[기업 정보]\n{company_profile_text}\n\n"
        f"[공고문 발췌]\n{evidence_block}\n\n"
        f"[판정할 요건]\n{criteria_block}"
    )
    logger.debug("secondary_filtering_judge_client 판정 프롬프트: %s", result)
    return result


async def judge_criteria(
    *,
    company_profile_text: str,
    criteria: list[tuple[str, str]],
    evidence_texts: list[str],
    client: AsyncOpenAI | None = None,
) -> dict[str, tuple[str, str | None]]:
    """criteria((criterion_id, statement) 목록)를 LLM에 판정시켜
    criterion_id -> (status, evidence) 딕셔너리를 반환한다.

    criteria가 비어 있으면 호출 없이 빈 딕셔너리를 반환한다. 재시도
    (OPENAI_MAX_RETRIES) 끝에도 실패하면 AiJudgeError를 던진다.
    """
    if not criteria:
        return {}

    settings = get_settings()
    active_client = client or _build_client()
    user_prompt = _build_user_prompt(
        company_profile_text=company_profile_text,
        criteria=criteria,
        evidence_texts=evidence_texts,
    )

    last_error: Exception | None = None
    for attempt in range(1, settings.OPENAI_MAX_RETRIES + 1):
        try:
            response = await active_client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
            )
        except _RETRYABLE_ERRORS as exc:
            last_error = exc
            logger.warning(
                "2차 필터링 LLM 판정 호출 실패 (attempt %s/%s): %s",
                attempt,
                settings.OPENAI_MAX_RETRIES,
                exc,
            )
            continue
        except OpenAIError as exc:
            raise AiJudgeError("2차 필터링 LLM 판정 호출에 실패했습니다.") from exc

        content = response.choices[0].message.content or ""
        try:
            parsed = _JudgeResponse.model_validate_json(content)
        except ValidationError as exc:
            last_error = exc
            logger.warning(
                "2차 필터링 LLM 판정 응답 파싱 실패 (attempt %s/%s): %s",
                attempt,
                settings.OPENAI_MAX_RETRIES,
                exc,
            )
            continue

        return {
            judgment.criterion_id: (
                judgment.status if judgment.status in _VALID_STATUSES else "정보부족",
                judgment.evidence,
            )
            for judgment in parsed.judgments
        }

    raise AiJudgeError(
        f"2차 필터링 LLM 판정 {settings.OPENAI_MAX_RETRIES}회 재시도 후 실패"
    ) from last_error
