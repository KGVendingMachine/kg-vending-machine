from datetime import date

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notice import Notice
from app.models.notice_source import NoticeSource


async def get_or_create_source(
    session: AsyncSession, source_name: str, base_url: str, collect_type: str
) -> NoticeSource:
    """공고 출처(기업마당/K-Startup)를 이름 기준으로 찾고, 없으면 새로 만든다.

    조회 후 삽입(select-then-insert) 방식은 두 수집 작업이 동시에 실행되면
    둘 다 "출처 없음"으로 판단해 같은 출처를 각각 생성하는 경쟁 상태가
    있었다. notice_source.source_name의 유니크 제약을 이용한
    INSERT ... ON CONFLICT DO NOTHING으로 원자적으로 처리한다.
    """
    stmt = (
        pg_insert(NoticeSource)
        .values(source_name=source_name, base_url=base_url, collect_type=collect_type)
        .on_conflict_do_nothing(index_elements=[NoticeSource.source_name])
        .returning(NoticeSource.id)
    )
    result = await session.execute(stmt)
    source_id = result.scalar_one_or_none()

    if source_id is None:
        result = await session.execute(
            select(NoticeSource).where(NoticeSource.source_name == source_name)
        )
        return result.scalar_one()

    return await session.get_one(NoticeSource, source_id)


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
                "updated_at": func.now(),
            },
        )
        .returning(Notice.id)
    )
    result = await session.execute(stmt)
    return result.scalar_one()


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
