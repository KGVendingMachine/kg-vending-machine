from datetime import date

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notice import Notice, NoticeAttachment, NoticeRegion, NoticeTargetType
from app.models.notice_source import NoticeSource
from app.models.organization import Organization
from app.models.raw import BizinfoRaw, KstartupRaw


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
    session: AsyncSession, notice_id: int, target_types: list[str]
) -> None:
    """공고의 신청대상 유형들을 최신 값으로 교체한다.

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
    if target_types:
        await session.execute(
            pg_insert(NoticeTargetType),
            [
                {"notice_id": notice_id, "target_type": target_type}
                for target_type in target_types
            ],
        )


async def replace_notice_region(
    session: AsyncSession,
    notice_id: int,
    regions: list[tuple[str, str]],
) -> None:
    """공고의 지원지역을 최신 값으로 교체한다. (delete를 항상 실행하는 이유는
    replace_notice_target_type과 동일)
    """
    await session.execute(
        delete(NoticeRegion).where(NoticeRegion.notice_id == notice_id)
    )
    if regions:
        await session.execute(
            pg_insert(NoticeRegion),
            [
                {
                    "notice_id": notice_id,
                    "region_code": region_code,
                    "region_name": region_name,
                }
                for region_code, region_name in regions
            ],
        )


async def find_notice_id_by_source_and_title(
    session: AsyncSession, source_name: str, title: str
) -> int | None:
    """특정 출처(source_name)에서 제목이 정확히 일치하는 공고의 id를 찾는다.

    기업마당과 K-Startup에 같은 사업이 각자 다른 external_id로 중복
    등록되는 경우가 있어, 제목 기준으로 다른 출처의 공고를 찾기 위해
    쓴다. 소스별 유일 키(external_id)가 서로 달라 그것만으로는
    중복을 판단할 수 없다.
    """
    result = await session.execute(
        select(Notice.id)
        .join(NoticeSource, Notice.source_id == NoticeSource.id)
        .where(NoticeSource.source_name == source_name, Notice.title == title)
    )
    return result.scalars().first()


async def delete_notice(session: AsyncSession, notice_id: int) -> None:
    """공고와 그에 딸린 신청대상/지역/원본 데이터를 삭제한다.

    notice_target_type/notice_region/bizinfo_raw/kstartup_raw는 모두
    notice에 대한 ON DELETE 규칙이 없어(기본 RESTRICT/NO ACTION),
    notice보다 먼저 지워야 FK 오류가 나지 않는다. 이 공고가 어느
    출처였는지 호출자가 알 필요 없도록 두 raw 테이블 모두에서 시도한다
    (해당 없는 쪽은 그냥 0행 삭제로 끝난다).
    """
    await session.execute(
        delete(NoticeTargetType).where(NoticeTargetType.notice_id == notice_id)
    )
    await session.execute(
        delete(NoticeRegion).where(NoticeRegion.notice_id == notice_id)
    )
    await session.execute(delete(BizinfoRaw).where(BizinfoRaw.notice_id == notice_id))
    await session.execute(delete(KstartupRaw).where(KstartupRaw.notice_id == notice_id))
    await session.execute(
        delete(NoticeAttachment).where(NoticeAttachment.notice_id == notice_id)
    )
    await session.execute(delete(Notice).where(Notice.id == notice_id))


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


async def save_attachment(
    session: AsyncSession,
    notice_id: int,
    file_name: str | None,
    file_url: str,
    file_type: str | None,
) -> None:
    """공고 첨부파일 메타데이터(URL/파일명)를 notice_attachment에 upsert한다.

    parsed_text(OCR 결과)는 여기서 채우지 않는다 — 전체 공고를 다 OCR하면
    비용이 커서, 매칭 후보로 좁혀진 공고만 그때 필요할 때 별도로 채운다
    (docs/matching-pipeline.md 4단계 참고).
    """
    stmt = (
        pg_insert(NoticeAttachment)
        .values(
            notice_id=notice_id,
            file_name=file_name,
            file_url=file_url,
            file_type=file_type,
        )
        .on_conflict_do_nothing(
            index_elements=[NoticeAttachment.notice_id, NoticeAttachment.file_url]
        )
    )
    await session.execute(stmt)
