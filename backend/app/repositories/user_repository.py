"""user 테이블 접근 계층.

SQLAlchemy 세션을 직접 다루는 유일한 계층. 커밋은 하지 않고,
호출하는 서비스가 트랜잭션 경계를 관리한다(notice 수집과 동일한 규칙).
"""

from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.business_plan import BusinessPlan, BusinessPlanChunk
from app.models.company import CompanyProfile
from app.models.match import MatchLog, MatchReport, MatchResult
from app.models.notice_bookmark import NoticeBookmark
from app.models.user import User


async def get_by_id(session: AsyncSession, user_id: int) -> User | None:
    """PK(id)로 유저를 조회한다. 없으면 None."""
    return await session.get(User, user_id)


async def get_by_kakao_id(session: AsyncSession, kakao_id: str) -> User | None:
    """카카오 회원번호로 유저를 조회한다. 없으면 None."""
    result = await session.execute(select(User).where(User.kakao_id == kakao_id))
    return result.scalar_one_or_none()


async def upsert_on_login(
    session: AsyncSession,
    *,
    kakao_id: str,
    email: str | None,
    name: str | None,
    nickname: str | None,
) -> User:
    """로그인 시 유저를 upsert하고 최종 로그인 시각을 갱신해 User를 반환한다.

    uq_user_kakao_id 유니크 제약을 이용한 INSERT ... ON CONFLICT로 처리해
    동시 로그인 요청이 겹쳐도 같은 kakao_id로 유저가 중복 생성되지 않는다.

    프로필(email/name/nickname)은 카카오 값으로 갱신하되, 사용자가 제공에
    동의하지 않아 값이 없을 때(None) 기존 값을 덮어써 지우지 않도록
    COALESCE(신규, 기존)를 쓴다.
    """
    insert_stmt = pg_insert(User).values(
        kakao_id=kakao_id,
        email=email,
        name=name,
        nickname=nickname,
        last_login_at=func.now(),
    )
    stmt = insert_stmt.on_conflict_do_update(
        index_elements=[User.kakao_id],
        set_={
            "email": func.coalesce(insert_stmt.excluded.email, User.email),
            "name": func.coalesce(insert_stmt.excluded.name, User.name),
            "nickname": func.coalesce(insert_stmt.excluded.nickname, User.nickname),
            "last_login_at": func.now(),
            "updated_at": func.now(),
        },
    ).returning(User.id)
    result = await session.execute(stmt)
    user_id = result.scalar_one()
    return await session.get_one(User, user_id)


async def withdraw(session: AsyncSession, user: User) -> None:
    """유저를 소프트 삭제한다: status=WITHDRAWN + 개인정보 익명화.

    email/name/nickname은 개인정보라 탈퇴 즉시 지운다. kakao_id는 남긴다 —
    같은 카카오 계정으로 다시 로그인하면 upsert_on_login이 이 행을 찾아
    재가입(reactivate) 처리할 수 있어야 하기 때문.
    """
    user.status = "WITHDRAWN"
    user.email = None
    user.name = None
    user.nickname = None
    user.updated_at = datetime.now()
    await session.flush()


async def reactivate(session: AsyncSession, user: User) -> None:
    """탈퇴(WITHDRAWN) 유저를 재가입 처리한다(status=ACTIVE).

    익명화로 지웠던 프로필은 로그인 upsert가 카카오 값으로 다시 채운다.
    """
    user.status = "ACTIVE"
    user.updated_at = datetime.now()
    await session.flush()


async def delete_owned_data(session: AsyncSession, user_id: int) -> list[str]:
    """탈퇴 시 유저에 딸린 데이터를 FK 순서대로 하드 삭제한다.

    company_profile/business_plan/match_log 모두 user에 대한 ON DELETE
    규칙이 없어(기본 RESTRICT), notice_repository.delete_notice와 같은
    방식으로 자식 → 부모 순서로 직접 지운다:
    match_result/match_report → match_log,
    business_plan_chunk → business_plan → company_profile.

    저장 파일(file_url)은 DB 트랜잭션 밖의 IO라 여기서 지우지 않고 경로만
    모아 반환한다 — 실제 삭제는 커밋 후 호출자(서비스)가 처리한다.
    """
    profile_ids = list(
        (
            await session.execute(
                select(CompanyProfile.id).where(CompanyProfile.user_id == user_id)
            )
        ).scalars()
    )

    file_paths: list[str] = []
    plan_ids: list[int] = []

    if profile_ids:
        file_paths.extend(
            (
                await session.execute(
                    select(CompanyProfile.file_url).where(
                        CompanyProfile.id.in_(profile_ids),
                        CompanyProfile.file_url.is_not(None),
                    )
                )
            ).scalars()
        )
        plan_ids = list(
            (
                await session.execute(
                    select(BusinessPlan.id).where(
                        BusinessPlan.company_profile_id.in_(profile_ids)
                    )
                )
            ).scalars()
        )

    if plan_ids:
        file_paths.extend(
            (
                await session.execute(
                    select(BusinessPlan.file_url).where(
                        BusinessPlan.id.in_(plan_ids),
                        BusinessPlan.file_url.is_not(None),
                    )
                )
            ).scalars()
        )

    log_ids = list(
        (
            await session.execute(
                select(MatchLog.id).where(MatchLog.user_id == user_id)
            )
        ).scalars()
    )

    if log_ids:
        await session.execute(
            delete(MatchResult).where(MatchResult.recommendation_run_id.in_(log_ids))
        )
        await session.execute(
            delete(MatchReport).where(MatchReport.match_run_id.in_(log_ids))
        )
        await session.execute(delete(MatchLog).where(MatchLog.id.in_(log_ids)))

    if plan_ids:
        await session.execute(
            delete(BusinessPlanChunk).where(
                BusinessPlanChunk.business_plan_id.in_(plan_ids)
            )
        )
        await session.execute(delete(BusinessPlan).where(BusinessPlan.id.in_(plan_ids)))

    await session.execute(
        delete(NoticeBookmark).where(NoticeBookmark.user_id == user_id)
    )

    if profile_ids:
        await session.execute(
            delete(CompanyProfile).where(CompanyProfile.id.in_(profile_ids))
        )

    await session.flush()
    return file_paths
