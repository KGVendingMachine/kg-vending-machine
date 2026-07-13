"""
services/msit_document_selector.py

과학기술정보통신부 사업공고 첨부파일 중 실제 "공고문" 1개를 골라낸다.

향후 2차 필터링(RAG, docs/matching-pipeline.md 4단계)에서 공고 원문을
벡터로 만들 때, 공고문 하나만 깔끔하게 필요하다 — 지금처럼 후보 전부를
넣으면 (1) 같은 내용의 hwpx/odt/hwp 중복본이 섞여 같은 텍스트가 여러 번
임베딩되고, (2) 신청서식/매뉴얼/법령 같은 부가자료가 섞여 벡터가
흐려진다. 정규화(옵션4, notice_normalization_service.py)처럼 "후보 전부
시도"하는 방식은 여기선 안 맞는다 — RAG는 벡터 하나로 합쳐야 하는 반면
정규화는 후보마다 독립된 LLM 결과를 비교해 고르는 것이라 성격이 다르다.

선택 흐름:
1) 포맷 필터: HWP/HWPX/PDF만 후보로 본다(ODT는 같은 내용의 중복 포맷,
   ZIP은 텍스트 추출 대상이 아니라 애초에 제외).
2) 규칙 기반 키워드 필터: "신청서식"/"매뉴얼"/"양식"/"법령"/"안내서"/
   "동의서" 등 부가자료 이름 패턴을 제외한다.
3) 그래도 여러 개 남으면(애매한 경우) LLM에게 파일명 목록을 주고
   실제 공고문 1개를 고르게 한다 — bizSupportNavigator(강사님 참고
   프로젝트)의 공고문 판별 방식과 동일한 패턴.
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

    LLM 호출이 실패하거나 응답을 못 알아들으면(비용/장애로 판단이 아예
    불가능한 상황), 첫 번째 후보로 조용히 폴백한다 - 공고문 후보 자체가
    없는 것보다는, 완벽하지 않아도 하나 고르는 게 2차 필터링 파이프라인
    전체를 막지 않는다.
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
