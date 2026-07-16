"""
repositories/secondary_filtering_judgment_repository.py

2차 필터링 LLM 판정 결과 캐시(secondary_filtering_judgment, 2026-07-16 RAG
성능 개선 검토로 추가) 전용 쿼리. (business_plan_id, notice_id,
profile_fingerprint) 조합으로 조회·저장한다 — 서비스 계층
(secondary_filtering_judge_service/matching_service)이 캐시 정책(언제
쓰고 언제 무효화할지)을 결정하고, 여기는 순수 CRUD만 담당한다.
"""

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.match import SecondaryFilteringJudgment


async def get_cached_judgment(
    session: AsyncSession,
    *,
    business_plan_id: int,
    notice_id: int,
    profile_fingerprint: str,
) -> SecondaryFilteringJudgment | None:
    result = await session.execute(
        select(SecondaryFilteringJudgment).where(
            SecondaryFilteringJudgment.business_plan_id == business_plan_id,
            SecondaryFilteringJudgment.notice_id == notice_id,
            SecondaryFilteringJudgment.profile_fingerprint == profile_fingerprint,
        )
    )
    return result.scalar_one_or_none()


async def save_judgment(
    session: AsyncSession,
    *,
    business_plan_id: int,
    notice_id: int,
    profile_fingerprint: str,
    score: float,
    excluded: bool,
    judgments: list[dict],
) -> None:
    """(business_plan_id, notice_id, profile_fingerprint) 조합으로 upsert한다.

    같은 조합이 이미 있으면(드물지만 동시 요청 등으로) 덮어쓴다 — 최신
    판정이 항상 우선이면 되므로 별도 버전 관리는 두지 않는다. flush만
    한다 — 매칭 파이프라인의 공유 세션 안에서 호출되므로 호출자가 트랜잭션
    경계를 관리한다(notice_embedding_service와 동일한 규칙).
    """
    stmt = (
        pg_insert(SecondaryFilteringJudgment)
        .values(
            business_plan_id=business_plan_id,
            notice_id=notice_id,
            profile_fingerprint=profile_fingerprint,
            score=score,
            excluded=excluded,
            judgments=judgments,
        )
        .on_conflict_do_update(
            constraint="uq_secondary_filtering_judgment_key",
            set_={
                "score": score,
                "excluded": excluded,
                "judgments": judgments,
                "judged_at": func.now(),
            },
        )
    )
    await session.execute(stmt)
    await session.flush()
