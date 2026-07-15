"""신청주체(기업 vs 비기업) 필터.

이 앱은 "기업 프로필" 대상이라 사용자는 항상 사업 주체다. 반면 수집한 공고
(특히 K-Startup)에는 일반인·대학생·청소년·대학·연구기관처럼 기업이 아닌
신청주체 "전용" 공고가 다수 섞여 있다(notice_target_type). 실제 사업자에게는
이런 공고가 무관하므로 후보에서 걸러낸다.

규모(소/중/중견)와 달리 "기업이냐 비기업이냐"는 target_type이 신뢰할 수 있게
알려주므로 하드 컷으로 안전하다(docs/matching-pipeline.md의 기업규모 하드컷
제외 결정과 대비 — 규모는 soft 스코어로만 쓴다).

예비창업자 예외: 아직 사업체가 없어 신분상 일반인/대학생일 수 있고, 창업
관련 일반인·대학생 대상 공고(예: 창업 아이디어 경진대회)가 유효할 수 있다.
그래서 실제 사업자(개인/법인)에게만 컷을 적용하고, 예비창업자·미입력은
컷하지 않는다(오탈락 방지).
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.notice_repository import get_notice_target_types_by_ids

# 기업이 아닌 신청주체 전용을 뜻하는 target_type. 실제 수집 데이터에서 확인된
# 값 기준(일반인/대학생/청소년/대학/연구기관). 여기 없는 값은 기업성일 수
# 있으므로 "확실히 비기업"인 것만 넣는다 — 잘못 거르는 위험을 최소화하려는
# 것이라, 목록을 넓히기보다 실측으로 확인된 값만 보수적으로 추가한다.
NON_COMPANY_TARGET_TYPES = frozenset(
    {"일반인", "대학생", "청소년", "대학", "연구기관"}
)

# 신청주체 컷을 적용할 사업자유형(실제 사업체가 있는 경우). 예비창업자는
# 제외한다(위 모듈 docstring의 예비창업자 예외 참고).
_REGISTERED_BUSINESS_TYPES = frozenset({"개인사업자", "법인사업자"})


def passes_applicant_type_filter(
    target_types: list[str], business_type: str | None
) -> bool:
    """이 공고가 해당 사업자유형의 신청주체 컷을 통과하는지 판정한다.

    - 실제 사업자(개인/법인)가 아니면(예비창업자·미입력) 컷하지 않고 통과.
    - 공고에 신청대상 정보가 없으면(대상 미상) 통과(안전).
    - 기업성 태그가 하나라도 있으면 통과. 모든 태그가 비기업 전용이면 제외.
    """
    if business_type not in _REGISTERED_BUSINESS_TYPES:
        return True
    if not target_types:
        return True
    return any(
        t.strip() not in NON_COMPANY_TARGET_TYPES for t in target_types if t.strip()
    )


async def filter_notice_ids_by_applicant_type(
    session: AsyncSession,
    notice_ids: list[int],
    business_type: str | None,
) -> list[int]:
    """신청주체 컷을 통과한 notice_id만 (입력 순서 유지) 반환한다.

    run_matching 등에서 후보 공고를 좁히는 한 단계로 조합해 쓰는 용도.
    실제 사업자가 아니면 컷이 없으므로 target_type 조회조차 생략한다.
    """
    if not notice_ids:
        return []
    if business_type not in _REGISTERED_BUSINESS_TYPES:
        return list(notice_ids)
    target_types_by_id = await get_notice_target_types_by_ids(session, notice_ids)
    return [
        notice_id
        for notice_id in notice_ids
        if passes_applicant_type_filter(
            target_types_by_id.get(notice_id, []), business_type
        )
    ]
