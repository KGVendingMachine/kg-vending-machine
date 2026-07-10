from datetime import date, datetime

from sqlalchemy import Integer, cast, delete, func, select, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.category import CategoryMapping, KgCategory
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

    populate_existing=True가 필요한 이유: 이 세션에서 같은 source_id가
    이미 한 번 로드된 적 있으면(예: 같은 세션 안에서 이 함수를 두 번
    호출), SQLAlchemy identity map이 방금 DO UPDATE로 반영한 최신 값
    대신 세션에 캐시된 예전 Python 객체를 그대로 돌려준다 — 위에서
    DO UPDATE를 쓴 이유 자체가 무력화되는 셈이라 명시적으로 다시
    읽어오게 한다.
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
    return await session.get_one(NoticeSource, source_id, populate_existing=True)


async def get_max_notice_external_id(
    session: AsyncSession, source_id: int
) -> int | None:
    """해당 출처에 저장된 공고 중 가장 큰 external_id(정수 변환)를 반환한다.

    K-Startup처럼 external_id가 순수 숫자 문자열(pbanc_sn)인 출처에서,
    "마지막으로 저장된 지점"을 조기종료 커서로 재활용하는 용도. 기업마당은
    external_id가 "PBLN_..." 접두사가 붙은 문자열이라 이 함수를 쓸 수 없다
    (get_max_bizinfo_registration_time을 대신 쓴다).
    """
    result = await session.execute(
        select(func.max(cast(Notice.external_id, Integer))).where(
            Notice.source_id == source_id
        )
    )
    return result.scalar_one_or_none()


async def get_max_bizinfo_registration_time(
    session: AsyncSession, source_id: int
) -> datetime | None:
    """저장된 기업마당 공고 중 원본 응답의 creatPnttm(등록시각) 최댓값을 반환한다.

    get_max_notice_external_id와 같은 이유로, notice_source.updated_at
    (수집 "시작" 시각)을 그대로 커서로 쓰지 않는다 — 그러면 페이지 중간에
    수집이 실패해도 이미 시작 시각이 커밋돼버려서, 다음 수집이 실패
    지점 이후를 영원히 건너뛸 위험이 있다. 대신 "실제로 저장에 성공한
    데이터" 기준으로 커서를 계산해 자기 보정되게 한다 — 이번 수집이
    일부만 성공해도 그만큼만 커서가 전진한다.

    creatPnttm 형식("YYYY-MM-DD HH:MM:SS")은 고정 자릿수라 문자열
    비교 순서가 시간 순서와 같아, SQL에서 문자열 그대로 MAX를 구해도
    정확하다.
    """
    result = await session.execute(
        select(func.max(cast(BizinfoRaw.field, JSONB)["creatPnttm"].astext))
        .join(Notice, Notice.id == BizinfoRaw.notice_id)
        .where(Notice.source_id == source_id)
    )
    max_str = result.scalar_one_or_none()
    if max_str is None:
        return None
    try:
        return datetime.strptime(max_str, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


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
    category_id: int | None = None,
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
            category_id=category_id,
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
                "category_id": category_id,
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

    DO NOTHING을 쓰면 재수집 시 원본 파일명이 바뀌어도 예전 값이 그대로
    남는다 (get_or_create_source에서 이미 겪은 것과 같은 문제라
    DO UPDATE로 처리). 단, parsed_text(OCR 결과)는 SET 대상에서 빼서,
    이미 OCR을 돌려둔 첨부파일의 결과가 재수집 때 지워지지 않게 한다
    (전체 공고를 다 OCR하면 비용이 커서, 매칭 후보로 좁혀진 공고만
    그때 필요할 때 별도로 채우는 구조 — docs/matching-pipeline.md 4단계).
    """
    stmt = (
        pg_insert(NoticeAttachment)
        .values(
            notice_id=notice_id,
            file_name=file_name,
            file_url=file_url,
            file_type=file_type,
        )
        .on_conflict_do_update(
            index_elements=[NoticeAttachment.notice_id, NoticeAttachment.file_url],
            set_={"file_name": file_name, "file_type": file_type},
        )
    )
    await session.execute(stmt)


async def set_attachment_parsed_text(
    session: AsyncSession, attachment_id: int, parsed_text: str
) -> None:
    """첨부파일 OCR 결과를 저장한다. save_attachment의 upsert는 재수집 시
    parsed_text를 건드리지 않으므로, OCR 결과 저장은 이 함수로 따로 한다."""
    await session.execute(
        update(NoticeAttachment)
        .where(NoticeAttachment.id == attachment_id)
        .values(parsed_text=parsed_text)
    )


async def get_category_mapping(session: AsyncSession) -> dict[str, int]:
    """원본 카테고리 키(예: "BIZINFO:금융") → kg_category.id 딕셔너리를 반환한다.

    (docs/notice-category-mapping.md, alembic 0756e6c105fe 시드 데이터 참고)
    """
    result = await session.execute(
        select(CategoryMapping.raw_category, CategoryMapping.category_id)
    )
    return dict(result.all())


async def set_notice_category(
    session: AsyncSession, notice_id: int, category_id: int
) -> None:
    """공고의 통합 카테고리를 지정한다."""
    await session.execute(
        update(Notice).where(Notice.id == notice_id).values(category_id=category_id)
    )


async def get_notices_for_status_refresh(
    session: AsyncSession,
) -> list[tuple[int, date | None, date | None, str | None]]:
    """마감 처리되지 않은 공고의 (id, 신청시작일, 신청종료일, 현재 상태) 목록을 반환한다.

    "마감"은 종단 상태로 보고 대상에서 제외한다 — 한 번 마감으로
    확정되면 신청기간이 다시 열리는 경우는 없다고 본다.
    """
    result = await session.execute(
        select(
            Notice.id,
            Notice.application_start_date,
            Notice.application_end_date,
            Notice.status,
        ).where(Notice.status.is_distinct_from("마감"))
    )
    return list(result.all())


async def update_notice_status(
    session: AsyncSession, notice_id: int, status: str, is_actionable: bool
) -> None:
    """공고의 모집 상태를 갱신한다 (마감일 경과 등으로 재계산된 값 반영)."""
    await session.execute(
        update(Notice)
        .where(Notice.id == notice_id)
        .values(status=status, is_actionable=is_actionable)
    )


async def get_notices_missing_category(
    session: AsyncSession, raw_model_cls
) -> list[tuple[int, str]]:
    """category_id가 비어있는 공고의 (notice_id, 원본 raw JSON) 목록을 반환한다.

    raw_model_cls는 BizinfoRaw 또는 KstartupRaw — 출처별로 원본 카테고리
    필드명이 달라 호출자가 어느 raw 테이블을 볼지 골라서 넘긴다. raw
    테이블과 조인하므로 결과는 자연히 해당 출처의 공고로 한정된다.
    """
    result = await session.execute(
        select(Notice.id, raw_model_cls.field)
        .join(raw_model_cls, raw_model_cls.notice_id == Notice.id)
        .where(Notice.category_id.is_(None))
    )
    return list(result.all())


async def get_bizinfo_notices_with_raw(session: AsyncSession) -> list[tuple[int, str]]:
    """기업마당 공고 전체의 (notice_id, 원본 raw JSON) 목록을 반환한다.

    _parse_bizinfo_regions 로직이 바뀌었을 때(예: 전국 판정 추가) 이미
    저장된 공고를 원본 hashtags 기준으로 재계산해 백필하는 용도.
    """
    result = await session.execute(
        select(Notice.id, BizinfoRaw.field).join(
            BizinfoRaw, BizinfoRaw.notice_id == Notice.id
        )
    )
    return list(result.all())


async def get_kstartup_notices_with_raw(session: AsyncSession) -> list[tuple[int, str]]:
    """K-Startup 공고 전체의 (notice_id, 원본 raw JSON) 목록을 반환한다.

    get_bizinfo_notices_with_raw와 같은 이유(REGION_CODE_BY_NAME 정정 시
    저장된 공고를 원본 supt_regin 기준으로 재계산해 백필하는 용도).
    """
    result = await session.execute(
        select(Notice.id, KstartupRaw.field).join(
            KstartupRaw, KstartupRaw.notice_id == Notice.id
        )
    )
    return list(result.all())


async def list_notices(
    session: AsyncSession,
    *,
    source_name: str | None = None,
    category_name: str | None = None,
    region_code: str | None = None,
    exclude_closed: bool = False,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[tuple[Notice, str, str | None]], int]:
    """조건에 맞는 공고 목록((Notice, 출처명, 카테고리명) 튜플)과 전체 건수를 반환한다.

    notice_region은 공고당 여러 행이라, LIMIT 걸기 전에 JOIN하면 지역이
    여러 개인 공고가 페이지네이션 개수를 왜곡한다(행이 늘어나 LIMIT 안에
    다른 공고가 덜 들어옴). region_code 필터는 유니크 제약(notice_id,
    region_code) 덕에 공고당 최대 1행만 매치되니 걸어도 안전하지만,
    지역 목록 자체는 여기서 같이 안 뽑고 호출자가 notice_id로 따로
    조회해야 한다.
    """
    query = (
        select(Notice, NoticeSource.source_name, KgCategory.name)
        .join(NoticeSource, NoticeSource.id == Notice.source_id)
        .outerjoin(KgCategory, KgCategory.id == Notice.category_id)
    )
    if region_code:
        query = query.join(
            NoticeRegion,
            (NoticeRegion.notice_id == Notice.id)
            & (NoticeRegion.region_code == region_code),
        )
    if source_name:
        query = query.where(NoticeSource.source_name == source_name)
    if category_name:
        query = query.where(KgCategory.name == category_name)
    if exclude_closed:
        query = query.where(Notice.status.is_distinct_from("마감"))

    total = await session.scalar(
        select(func.count()).select_from(query.with_only_columns(Notice.id).subquery())
    )

    result = await session.execute(
        query.order_by(Notice.id.desc()).limit(limit).offset(offset)
    )
    return list(result.all()), total or 0


async def get_notice_regions_by_ids(
    session: AsyncSession, notice_ids: list[int]
) -> dict[int, list[str]]:
    """notice_id -> 지역명 목록 딕셔너리. list_notices 결과에 붙여쓰는 용도."""
    if not notice_ids:
        return {}
    result = await session.execute(
        select(NoticeRegion.notice_id, NoticeRegion.region_name).where(
            NoticeRegion.notice_id.in_(notice_ids)
        )
    )
    regions: dict[int, list[str]] = {}
    for notice_id, region_name in result.all():
        regions.setdefault(notice_id, []).append(region_name)
    return regions


async def get_notice_detail(
    session: AsyncSession, notice_id: int
) -> tuple[Notice, str, str | None] | None:
    """공고 하나를 (Notice, 출처명, 카테고리명) 튜플로 반환한다. 없으면 None."""
    result = await session.execute(
        select(Notice, NoticeSource.source_name, KgCategory.name)
        .join(NoticeSource, NoticeSource.id == Notice.source_id)
        .outerjoin(KgCategory, KgCategory.id == Notice.category_id)
        .where(Notice.id == notice_id)
    )
    return result.first()


async def get_notice_target_types(session: AsyncSession, notice_id: int) -> list[str]:
    result = await session.execute(
        select(NoticeTargetType.target_type).where(
            NoticeTargetType.notice_id == notice_id
        )
    )
    return list(result.scalars().all())


async def get_notice_regions(session: AsyncSession, notice_id: int) -> list[str]:
    result = await session.execute(
        select(NoticeRegion.region_name).where(NoticeRegion.notice_id == notice_id)
    )
    return list(result.scalars().all())


async def get_notice_region_codes(session: AsyncSession, notice_id: int) -> set[str]:
    """공고에 저장된 region_code 집합을 반환한다.

    get_notice_regions(이름 목록)와 별개로, 지역 코드 정정 백필에서
    "재계산한 결과가 기존과 실제로 다른지"를 정확히 비교하는 용도.
    """
    result = await session.execute(
        select(NoticeRegion.region_code).where(NoticeRegion.notice_id == notice_id)
    )
    return set(result.scalars().all())


async def get_notice_attachments(
    session: AsyncSession, notice_id: int
) -> list[NoticeAttachment]:
    result = await session.execute(
        select(NoticeAttachment).where(NoticeAttachment.notice_id == notice_id)
    )
    return list(result.scalars().all())
