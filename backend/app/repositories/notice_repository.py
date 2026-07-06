from datetime import date

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notice import Notice, NoticeRegion, NoticeTargetType
from app.models.notice_source import NoticeSource
from app.models.organization import Organization


async def get_or_create_source(
    session: AsyncSession, source_name: str, base_url: str, collect_type: str
) -> NoticeSource:
    """공고 출처(기업마당/K-Startup)를 이름 기준으로 찾아 upsert한다.

    조회 후 삽입(select-then-insert) 방식은 두 수집 작업이 동시에 실행되면
    둘 다 "출처 없음"으로 판단해 같은 출처를 각각 생성하는 경쟁 상태가
    있었다. notice_source.source_name의 유니크 제약을 이용한
    INSERT ... ON CONFLICT로 원자적으로 처리한다.

    DO NOTHING이 아니라 DO UPDATE를 쓰는 이유: DO NOTHING이면 이미 있는
    출처의 base_url/collect_type이 바뀌어도 호출자가 넘긴 최신 값이
    무시되고 예전 값이 그대로 남았다.
    """
    stmt = (
        pg_insert(NoticeSource)
        .values(source_name=source_name, base_url=base_url, collect_type=collect_type)
        .on_conflict_do_update(
            index_elements=[NoticeSource.source_name],
            set_={
                "base_url": base_url,
                "collect_type": collect_type,
                "updated_at": func.now(),
            },
        )
        .returning(NoticeSource.id)
    )
    result = await session.execute(stmt)
    source_id = result.scalar_one()
    return await session.get_one(NoticeSource, source_id)


async def get_or_create_organization(session: AsyncSession, name: str) -> Organization:
    """기관명으로 Organization을 찾고, 없으면 새로 만든다.

    get_or_create_source와 동일한 이유로 조회 후 삽입 대신 원자적
    upsert 패턴을 쓴다.
    """
    stmt = (
        pg_insert(Organization)
        .values(name=name)
        .on_conflict_do_nothing(index_elements=[Organization.name])
        .returning(Organization.id)
    )
    result = await session.execute(stmt)
    org_id = result.scalar_one_or_none()

    if org_id is None:
        result = await session.execute(
            select(Organization).where(Organization.name == name)
        )
        return result.scalar_one()

    return await session.get_one(Organization, org_id)


async def upsert_notice(
    session: AsyncSession,
    *,
    source_id: int,
    external_id: str,
    title: str | None,
    organization_id: int | None = None,
    notice_group_key: str | None = None,
    application_start_date: date | None,
    application_end_date: date | None,
    status: str | None,
    is_actionable: bool | None,
    source_url: str | None,
    apply_url: str | None,
    summary_text: str | None,
) -> int:
    """(source_id, external_id) 기준으로 공고를 upsert하고 notice.id를 반환한다.

    동일 공고를 다시 수집해도 새 행이 생기지 않고 기존 행이 갱신되도록
    notice(source_id, external_id) 유니크 제약을 이용한 ON CONFLICT를 쓴다.

    notice.external_id 컬럼 자체는 NULL을 허용하지만(수동 등록 등 다른
    경로를 위해), PostgreSQL UNIQUE 제약은 NULL끼리는 중복으로 보지 않아
    이 함수로 external_id=NULL을 넣으면 중복 방지가 무력화된다. 이 함수는
    수집 파이프라인 전용이라 항상 값이 있어야 하므로 여기서 막는다.
    """
    if not external_id:
        raise ValueError("upsert_notice: external_id는 비어 있을 수 없습니다")

    stmt = (
        pg_insert(Notice)
        .values(
            source_id=source_id,
            external_id=external_id,
            title=title,
            organization_id=organization_id,
            notice_group_key=notice_group_key,
            application_start_date=application_start_date,
            application_end_date=application_end_date,
            status=status,
            is_actionable=is_actionable,
            source_url=source_url,
            apply_url=apply_url,
            summary_text=summary_text,
        )
        .on_conflict_do_update(
            index_elements=[Notice.source_id, Notice.external_id],
            set_={
                "title": title,
                "organization_id": organization_id,
                "notice_group_key": notice_group_key,
                "application_start_date": application_start_date,
                "application_end_date": application_end_date,
                "status": status,
                "is_actionable": is_actionable,
                "source_url": source_url,
                "apply_url": apply_url,
                "summary_text": summary_text,
                "updated_at": func.now(),
            },
        )
        .returning(Notice.id)
    )
    result = await session.execute(stmt)
    return result.scalar_one()


async def replace_notice_target_type(
    session: AsyncSession, notice_id: int, target_type: str | None
) -> None:
    """공고의 신청대상 유형을 최신 값으로 교체한다.

    ON CONFLICT DO NOTHING으로 추가만 하면, 공고를 재수집했을 때
    신청대상이 바뀌거나 없어져도 예전 값이 계속 남아있는 문제가 있었다.
    해당 공고의 기존 값을 지우고 이번에 수집한 값으로 다시 넣는다.

    delete는 target_type이 비어 있어도(이번 응답에 값이 없는 경우) 항상
    실행해야 한다. 호출자가 값이 있을 때만 이 함수를 호출하면, 응답에서
    값이 사라진 경우 예전 값이 지워지지 않고 그대로 남기 때문이다.
    """
    await session.execute(
        delete(NoticeTargetType).where(NoticeTargetType.notice_id == notice_id)
    )
    if target_type:
        await session.execute(
            pg_insert(NoticeTargetType).values(
                notice_id=notice_id, target_type=target_type
            )
        )


async def replace_notice_region(
    session: AsyncSession,
    notice_id: int,
    region_code: str | None,
    region_name: str | None,
) -> None:
    """공고의 지원지역을 최신 값으로 교체한다. (delete를 항상 실행하는 이유는
    replace_notice_target_type과 동일)
    """
    await session.execute(
        delete(NoticeRegion).where(NoticeRegion.notice_id == notice_id)
    )
    if region_code:
        await session.execute(
            pg_insert(NoticeRegion).values(
                notice_id=notice_id, region_code=region_code, region_name=region_name
            )
        )


async def save_raw(
    session: AsyncSession, raw_model_cls, key: str, field: str, notice_id: int
) -> None:
    """원본 API 응답(JSON 문자열)을 raw 테이블에 upsert한다."""
    stmt = (
        pg_insert(raw_model_cls)
        .values(key=key, field=field, notice_id=notice_id)
        .on_conflict_do_update(
            index_elements=[raw_model_cls.key],
            set_={"field": field, "notice_id": notice_id},
        )
    )
    await session.execute(stmt)
