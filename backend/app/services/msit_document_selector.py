"""과학기술정보통신부 사업공고 첨부파일 중 실제 "공고문" 1개를 골라낸다.

포맷 필터 -> 부가자료 키워드 필터 -> (그래도 여럿이면) LLM 판단 순으로 좁혀나간다.
"""

import json
import logging

from openai import AsyncOpenAI, OpenAIError

from app.core.config import get_settings
from app.models.notice import NoticeAttachment

logger = logging.getLogger(__name__)

_TARGET_FILE_TYPES = {"HWP", "HWPX", "PDF"}

# 실제 응답 샘플(2026-07-13)에서 확인한 부가자료 파일명 패턴 - 신청서식/
# 안내서/매뉴얼/법령/동의서류는 공고문 본문이 아니다.
_SUPPLEMENTARY_KEYWORDS = (
    "신청서식",
    "서식",
    "안내서",
    "매뉴얼",
    "양식",
    "법령",
    "동의서",
)


def _is_supplementary_document(file_name: str | None) -> bool:
    """파일명에 부가자료 키워드(신청서식/안내서 등)가 포함되는지 확인한다."""
    if not file_name:
        return False
    return any(keyword in file_name for keyword in _SUPPLEMENTARY_KEYWORDS)


_SELECT_SYSTEM_PROMPT = (
    "여러 첨부파일 이름 중에서 실제 '공고문' 본문에 해당하는 파일 하나를 "
    "고르세요. 신청서식·안내서·매뉴얼·양식·법령·동의서류는 공고문이 "
    "아닙니다. 반드시 주어진 목록 중 하나의 인덱스만 JSON으로 답하세요: "
    '{"index": 0}'
)


async def _select_via_llm(
    candidates: list[NoticeAttachment], *, client: AsyncOpenAI | None = None
) -> NoticeAttachment:
    """규칙 필터로도 못 좁힌 애매한 후보를 LLM이 최종 선택한다.

    LLM 호출/응답 파싱이 실패하면 첫 번째 후보로 조용히 폴백해 파이프라인을 막지 않는다.
    """
    settings = get_settings()
    active_client = client or AsyncOpenAI(
        api_key=settings.OPENAI_API_KEY, timeout=settings.OPENAI_TIMEOUT_SECONDS
    )
    file_names = [candidate.file_name or "" for candidate in candidates]
    user_prompt = "파일명 목록:\n" + "\n".join(
        f"{i}: {name}" for i, name in enumerate(file_names)
    )

    try:
        response = await active_client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": _SELECT_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        )
        content = response.choices[0].message.content or "{}"
        index = json.loads(content)["index"]
        return candidates[int(index)]
    except (OpenAIError, ValueError, KeyError, IndexError, TypeError):
        logger.exception(
            "공고문 선택 LLM 판단 실패, 첫 번째 후보로 폴백 (candidates=%s)",
            file_names,
        )
        return candidates[0]


async def select_msit_announcement_attachment(
    attachments: list[NoticeAttachment],
) -> NoticeAttachment | None:
    """공고 첨부파일 목록에서 실제 공고문 1개를 고른다. 후보가 없으면 None."""
    format_candidates = [a for a in attachments if a.file_type in _TARGET_FILE_TYPES]
    if not format_candidates:
        return None
    if len(format_candidates) == 1:
        return format_candidates[0]

    keyword_filtered = [
        a for a in format_candidates if not _is_supplementary_document(a.file_name)
    ]
    # 전부 부가자료 키워드에 걸리는 경우(과탐지 위험) 필터 적용 전 후보로
    # 되돌린다 - 아예 후보가 0개가 되는 것보다 낫다.
    candidates = keyword_filtered if keyword_filtered else format_candidates
    if len(candidates) == 1:
        return candidates[0]

    return await _select_via_llm(candidates)
