from datetime import date

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notice import Notice
from app.models.notice_source import NoticeSource


async def get_or_create_source(
    session: AsyncSession, source_name: str, base_url: str, collect_type: str
) -> NoticeSource:
    """공고 출처(기업마당/K-Startup)를 이름 기준으로 찾고, 없으면 새로 만든다."""
    result = await session.execute(
        select(NoticeSource).where(NoticeSource.source_name == source_name)
    )
    source = result.scalar_one_or_none()
    if source is not None:
        return source

    source = NoticeSource(
        source_name=source_name, base_url=base_url, collect_type=collect_type
    )
    session.add(source)
    await session.flush()
    return source


async def upsert_notice(
    session: AsyncSession,
    *,
    source_id: int,
    external_id: str,
    title: str | None,
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
    """
    stmt = (
        pg_insert(Notice)
        .values(
            source_id=source_id,
            external_id=external_id,
            title=title,
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
                "application_start_date": application_start_date,
                "application_end_date": application_end_date,
                "status": status,
                "is_actionable": is_actionable,
                "source_url": source_url,
                "apply_url": apply_url,
                "summary_text": summary_text,
            },
        )
        .returning(Notice.id)
    )
    result = await session.execute(stmt)
    return result.scalar_one()


async def save_raw(session: AsyncSession, raw_model_cls, key: str, field: str, notice_id: int) -> None:
    """원본 API 응답(JSON 문자열)을 raw 테이블에 upsert한다.

    BizinfoRaw/KstartupRaw는 실제 DB 컬럼명이 "Key"/"Field"/"id"로,
    파이썬 속성명(key/field/notice_id)과 다르게 매핑되어 있다. ORM 클래스로
    on_conflict_do_update를 만들면 SET절이 속성명 기준으로 잘못 렌더링되므로,
    실제 컬럼명을 아는 Core Table(__table__)을 직접 사용한다.
    """
    table = raw_model_cls.__table__
    stmt = (
        pg_insert(table)
        .values(**{"Key": key, "Field": field, "id": notice_id})
        .on_conflict_do_update(
            index_elements=["Key"],
            set_={"Field": field, "id": notice_id},
        )
    )
    await session.execute(stmt)
