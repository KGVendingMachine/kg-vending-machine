"""match_log 테이블 접근 계층.

커밋은 하지 않고 호출하는 쪽이 트랜잭션 경계를 관리한다(company_repository와
동일 규칙). 리스트 조회는 어떤 파일로 돌린 매칭인지 보여줄 수 있게
business_plan.title을 함께 돌려준다.
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import and_, delete, null, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.business_plan import BusinessPlan
from app.models.category import KgCategory
from app.models.match import MatchLog, MatchReport, MatchResult
from app.models.notice import Notice
from app.models.notice_bookmark import NoticeBookmark
from app.models.organization import Organization


async def create(
    session: AsyncSession,
    *,
    user_id: int,
    company_profile_id: int,
    business_plan_id: int,
    run_status: str,
    query_text: str | None = None,
    query_json: dict | None = None,
    completed_at: datetime | None = None,
) -> MatchLog:
    """매칭 실행 로그 한 행을 만든다. flush로 id만 채우고 커밋은 안 한다."""
    log = MatchLog(
        user_id=user_id,
        company_profile_id=company_profile_id,
        business_plan_id=business_plan_id,
        run_status=run_status,
        query_text=query_text,
        query_json=query_json,
        completed_at=completed_at,
    )
    session.add(log)
    await session.flush()
    return log


async def list_by_user(
    session: AsyncSession, user_id: int, *, limit: int = 20, offset: int = 0
) -> list[tuple[MatchLog, str | None]]:
    """유저의 매칭 로그를 최신순으로 (로그, 사업계획서 제목) 쌍으로 반환한다.

    business_plan_id가 NULL인 행도 있을 수 있어(스키마상 허용) outer join.
    "더보기"식 페이지네이션을 위해 offset을 받는다.
    """
    result = await session.execute(
        select(MatchLog, BusinessPlan.title)
        .join(BusinessPlan, MatchLog.business_plan_id == BusinessPlan.id, isouter=True)
        .where(MatchLog.user_id == user_id)
        .order_by(MatchLog.created_at.desc(), MatchLog.id.desc())
        .offset(offset)
        .limit(limit)
    )
    return [(row[0], row[1]) for row in result.all()]


async def get_owned_by_user(
    session: AsyncSession, match_log_id: int, user_id: int
) -> tuple[MatchLog, str | None] | None:
    """유저 소유의 매칭 로그 한 건을 (로그, 사업계획서 제목)으로 반환한다.

    없거나 남의 로그면 None — 호출부가 존재 여부를 노출하지 않고 404로 답한다.
    """
    result = await session.execute(
        select(MatchLog, BusinessPlan.title)
        .join(BusinessPlan, MatchLog.business_plan_id == BusinessPlan.id, isouter=True)
        .where(MatchLog.id == match_log_id, MatchLog.user_id == user_id)
    )
    row = result.one_or_none()
    if row is None:
        return None
    return (row[0], row[1])


async def delete_owned_by_user(
    session: AsyncSession, match_log_id: int, user_id: int
) -> bool:
    """유저 소유의 매칭 로그 한 건을 자식 레코드와 함께 삭제한다.

    match_result/match_report는 match_log에 대해 ON DELETE 규칙이 없어(기본
    RESTRICT) 자식부터 지워야 FK 제약을 피할 수 있다
    (user_repository.delete_owned_data의 회원탈퇴 삭제 순서와 동일 규칙).
    없거나 남의 로그면 False — 커밋은 호출자가 한다.
    """
    row = await get_owned_by_user(session, match_log_id, user_id)
    if row is None:
        return False
    await session.execute(
        delete(MatchResult).where(MatchResult.recommendation_run_id == match_log_id)
    )
    await session.execute(
        delete(MatchReport).where(MatchReport.match_run_id == match_log_id)
    )
    await session.execute(delete(MatchLog).where(MatchLog.id == match_log_id))
    return True


async def get_result_owned_by_user(
    session: AsyncSession, match_result_id: int, user_id: int
) -> MatchResult | None:
    """유저 소유의 추천 결과 한 건을 반환한다(소유권은 match_log.user_id 경유).

    없거나 남의 결과면 None. 북마크가 추천 카드에서 담을 때 이 결과로부터
    notice_id·business_plan_id 맥락을 끌어온다.
    """
    result = await session.execute(
        select(MatchResult)
        .join(MatchLog, MatchLog.id == MatchResult.recommendation_run_id)
        .where(MatchResult.id == match_result_id, MatchLog.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def get_business_plan_id_for_result(
    session: AsyncSession, match_result_id: int
) -> int | None:
    """추천 결과가 어느 사업계획서로 매칭됐는지(match_log.business_plan_id) 반환한다."""
    result = await session.execute(
        select(MatchLog.business_plan_id)
        .join(MatchResult, MatchResult.recommendation_run_id == MatchLog.id)
        .where(MatchResult.id == match_result_id)
    )
    return result.scalar_one_or_none()


async def list_normalized_notice_candidates(
    session: AsyncSession,
    *,
    notice_ids: list[int] | None = None,
) -> list[Notice]:
    if notice_ids == []:
        return []

    conditions = [
        Notice.normalized_json.is_not(None),
        Notice.normalization_status == "completed",
        Notice.is_actionable.is_not(False),
    ]
    if notice_ids is not None:
        conditions.append(Notice.id.in_(notice_ids))

    result = await session.execute(
        select(Notice)
        .where(*conditions)
        .order_by(Notice.application_end_date.asc().nulls_last(), Notice.id.desc())
    )
    return list(result.scalars().all())


async def replace_results(
    session: AsyncSession, match_log_id: int, results: list[MatchResult]
) -> None:
    await session.execute(
        delete(MatchResult).where(MatchResult.recommendation_run_id == match_log_id)
    )
    if results:
        session.add_all(results)
        await session.flush()


@dataclass(frozen=True)
class MatchResultWithNotice:
    """결과 페이지 카드 표시에 필요한 공고 정보를 결과와 함께 담는다."""

    result: MatchResult
    notice: Notice
    organization_name: str | None
    category_name: str | None
    bookmark_id: int | None = None
    """이 카드가 (해당 유저·이 실행의 사업계획서 기준으로) 담겨 있으면 그 북마크 id.
    별표 채움/해제 표시에 쓴다. 담지 않았으면 None."""


async def list_results_by_log(
    session: AsyncSession,
    match_log_id: int,
    *,
    user_id: int | None = None,
    business_plan_id: int | None = None,
) -> list[MatchResultWithNotice]:
    """한 매칭 실행의 결과들을 적합도 내림차순으로, 공고 정보와 함께 반환한다.

    user_id 를 주면 각 결과 공고가 (그 유저, 이 실행의 사업계획서) 기준으로
    이미 북마크됐는지도 함께 조인해 bookmark_id 로 돌려준다(별표 표시용).
    담김 판정은 match_result_id 가 아니라 (notice, business_plan) 단위다 —
    같은 계획서면 다른 실행에서 담았어도 담긴 것으로 본다.
    """
    columns = [MatchResult, Notice, Organization.name, KgCategory.name]
    stmt = (
        select(*columns, NoticeBookmark.id if user_id is not None else null())
        .join(Notice, Notice.id == MatchResult.notice_id)
        .join(Organization, Notice.organization_id == Organization.id, isouter=True)
        .join(KgCategory, Notice.category_id == KgCategory.id, isouter=True)
    )
    if user_id is not None:
        plan_pred = (
            NoticeBookmark.business_plan_id.is_(None)
            if business_plan_id is None
            else NoticeBookmark.business_plan_id == business_plan_id
        )
        stmt = stmt.join(
            NoticeBookmark,
            and_(
                NoticeBookmark.notice_id == MatchResult.notice_id,
                NoticeBookmark.user_id == user_id,
                plan_pred,
            ),
            isouter=True,
        )
    stmt = stmt.where(MatchResult.recommendation_run_id == match_log_id).order_by(
        MatchResult.total_score.desc().nulls_last(), MatchResult.id.asc()
    )
    result = await session.execute(stmt)
    return [
        MatchResultWithNotice(
            result=row[0],
            notice=row[1],
            organization_name=row[2],
            # KgCategory.name은 Enum 컬럼이라 멤버로 올 수 있어 표시값으로 푼다.
            category_name=getattr(row[3], "value", row[3]),
            bookmark_id=row[4],
        )
        for row in result.all()
    ]
