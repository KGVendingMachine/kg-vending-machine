"""1차 필터(하드필터) 후보 공고 조회.

기업 프로필 기준 하드필터(services/notice_eligibility_service)가 4축
(지역/대상/업력/기간)을 판정할 수 있도록, 공고 본체 컬럼과 자식 테이블
(지역 코드·신청대상)을 한 번에 모아 후보 행 목록으로 반환한다.

축 판정 자체는 서비스 계층에서 하고(축별 탈락 집계가 필요해 순차 파이썬
필터가 맞다), 이 리포지토리는 판정에 필요한 데이터를 N+1 없이 벌크로
읽어오는 역할만 한다.
"""

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notice import Notice, NoticeRegion, NoticeTargetType


@dataclass(frozen=True)
class NoticeEligibilityRow:
    """1차 필터 한 건에 필요한 공고 데이터."""

    notice_id: int
    status: str | None
    application_start_date: date | None
    application_end_date: date | None
    target_business_years_max: int | None
    target_allows_prestartup: bool | None
    region_codes: frozenset[str]
    target_types: tuple[str, ...]


async def get_eligibility_candidates(
    session: AsyncSession,
) -> list[NoticeEligibilityRow]:
    """하드필터 후보 공고 전체를 판정용 데이터와 함께 반환한다.

    후보 = 저장된 공고 전부. 기간 축이 파이프라인 안에서 탈락을 집계하므로
    (마감/예정도 후보로 세어 counts에 반영) 여기서 상태로 미리 거르지 않는다.
    지역/대상은 공고당 여러 행이라 각각 벌크로 읽어 notice_id로 묶는다.
    """
    notice_result = await session.execute(
        select(
            Notice.id,
            Notice.status,
            Notice.application_start_date,
            Notice.application_end_date,
            Notice.target_business_years_max,
            Notice.target_allows_prestartup,
        )
    )

    region_result = await session.execute(
        select(NoticeRegion.notice_id, NoticeRegion.region_code)
    )
    region_codes_by_notice: dict[int, set[str]] = {}
    for notice_id, region_code in region_result.all():
        region_codes_by_notice.setdefault(notice_id, set()).add(region_code)

    target_result = await session.execute(
        select(NoticeTargetType.notice_id, NoticeTargetType.target_type)
    )
    target_types_by_notice: dict[int, list[str]] = {}
    for notice_id, target_type in target_result.all():
        target_types_by_notice.setdefault(notice_id, []).append(target_type)

    rows: list[NoticeEligibilityRow] = []
    for (
        notice_id,
        status,
        start_date,
        end_date,
        years_max,
        allows_prestartup,
    ) in notice_result.all():
        rows.append(
            NoticeEligibilityRow(
                notice_id=notice_id,
                status=status,
                application_start_date=start_date,
                application_end_date=end_date,
                target_business_years_max=years_max,
                target_allows_prestartup=allows_prestartup,
                region_codes=frozenset(region_codes_by_notice.get(notice_id, ())),
                target_types=tuple(target_types_by_notice.get(notice_id, ())),
            )
        )
    return rows
