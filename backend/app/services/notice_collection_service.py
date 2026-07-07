import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.crawler.bizinfo_client import fetch_bizinfo_notices
from app.crawler.kstartup_client import fetch_kstartup_notices
from app.models.raw import BizinfoRaw, KstartupRaw
from app.repositories.notice_repository import (
    delete_notice,
    find_notice_id_by_source_and_title,
    get_or_create_organization,
    get_or_create_source,
    replace_notice_region,
    replace_notice_target_type,
    save_raw,
    upsert_notice,
)

logger = logging.getLogger(__name__)

BIZINFO_SOURCE_NAME = "기업마당"
KSTARTUP_SOURCE_NAME = "K-Startup"

REGION_CODE_BY_NAME = {
    "전국": "ALL",
    "서울": "11",
    "서울특별시": "11",
    "부산": "26",
    "부산광역시": "26",
    "대구": "27",
    "대구광역시": "27",
    "인천": "28",
    "인천광역시": "28",
    "광주": "29",
    "광주광역시": "29",
    "대전": "30",
    "대전광역시": "30",
    "울산": "31",
    "울산광역시": "31",
    "세종": "36",
    "세종특별자치시": "36",
    "경기": "41",
    "경기도": "41",
    "충북": "43",
    "충청북도": "43",
    "충남": "44",
    "충청남도": "44",
    "전남": "46",
    "전라남도": "46",
    "경북": "47",
    "경상북도": "47",
    "경남": "48",
    "경상남도": "48",
    "제주": "50",
    "제주특별자치도": "50",
    "강원": "51",
    "강원특별자치도": "51",
    "전북": "52",
    "전북특별자치도": "52",
}


@dataclass
class CollectionResult:
    saved_count: int = 0
    failed_count: int = 0
    failed_ids: list[str] = field(default_factory=list)


def _split_multi_value(value: str | None) -> list[str]:
    """API의 쉼표/세미콜론/줄바꿈/파이프 구분 문자열을 중복 없는 값으로 나눈다."""
    if not value:
        return []
    return list(
        dict.fromkeys(
            part.strip() for part in re.split(r"[,;|\r\n]+", value) if part.strip()
        )
    )


def _parse_bizinfo_date_range(value: str | None) -> tuple[date | None, date | None]:
    """ "2026-07-27 ~ 2026-07-30" 형식 문자열을 (시작일, 종료일)로 변환한다."""
    if not value or "~" not in value:
        return None, None
    start_raw, end_raw = (part.strip() for part in value.split("~", 1))
    try:
        start = datetime.strptime(start_raw, "%Y-%m-%d").date()
        end = datetime.strptime(end_raw, "%Y-%m-%d").date()
        return start, end
    except ValueError:
        # 조용히 None을 반환하면 API 응답 형식이 바뀌어도 알아챌 방법이
        # 없어서, 형식이 안 맞을 때는 경고 로그를 남긴다.
        logger.warning("기업마당 신청기간 형식을 해석하지 못했습니다: %r", value)
        return None, None


def _parse_kstartup_date(value: str | None) -> date | None:
    """ "YYYYMMDD" 형식 문자열을 date로 변환한다."""
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except ValueError:
        logger.warning("K-Startup 날짜 형식을 해석하지 못했습니다: %r", value)
        return None


def _parse_regions(value: str | None) -> list[tuple[str, str]]:
    """지역명들을 광역자치단체 코드와 이름의 목록으로 변환한다."""
    regions: list[tuple[str, str]] = []
    seen_codes: set[str] = set()
    for region_name in _split_multi_value(value):
        region_code = REGION_CODE_BY_NAME.get(region_name)
        if region_code is None:
            logger.warning("지원지역 코드를 찾지 못했습니다: %r", region_name)
            continue
        if region_code in seen_codes:
            continue
        seen_codes.add(region_code)
        regions.append((region_code, region_name))
    return regions


def _derive_status_from_dates(
    start_date: date | None, end_date: date | None
) -> tuple[str, bool]:
    """기업마당 모집 상태를 신청 시작일과 종료일 기준으로 추정한다.

    실제 상태 플래그가 존재하는지는 COL-002(정규화) 단계에서 원본 raw
    데이터를 보며 다시 검토가 필요할 수 있다. 지금은 수집·적재만 다룬다.
    """
    today = date.today()
    if start_date is not None and start_date > today:
        return "예정", False
    if end_date is not None and end_date < today:
        return "마감", False
    if start_date is not None and end_date is not None:
        return "모집중", True
    return "확인필요", False


async def _process_bizinfo_item(
    session: AsyncSession,
    source_id: int,
    item: dict,
    collection_result: CollectionResult,
) -> None:
    """기업마당 공고 한 건을 처리해 collection_result에 결과를 반영한다."""
    if not isinstance(item, dict):
        return
    pblanc_id = item.get("pblancId")
    if not pblanc_id:
        return
    external_id = str(pblanc_id)

    try:
        async with session.begin_nested():
            start_date, end_date = _parse_bizinfo_date_range(
                item.get("reqstBeginEndDe")
            )
            status, is_actionable = _derive_status_from_dates(start_date, end_date)

            organization_id = None
            organization_name = item.get("jrsdInsttNm")
            if organization_name:
                organization = await get_or_create_organization(
                    session, organization_name
                )
                organization_id = organization.id

            title = item.get("pblancNm")
            notice_id = await upsert_notice(
                session,
                source_id=source_id,
                external_id=external_id,
                title=title,
                organization_id=organization_id,
                # 기업마당 응답에는 재공고/연장공고를 나타내는 필드가
                # 확인되지 않아 notice_group_key는 비워둔다
                # (K-Startup의 intg_pbanc_yn과 달리 별도 이슈로 조사 필요).
                notice_group_key=None,
                application_start_date=start_date,
                application_end_date=end_date,
                status=status,
                is_actionable=is_actionable,
                source_url=item.get("pblancUrl"),
                apply_url=item.get("rceptEngnHmpgUrl"),
                summary_text=item.get("bsnsSumryCn"),
            )
            await save_raw(
                session,
                BizinfoRaw,
                key=external_id,
                field=json.dumps(item, ensure_ascii=False),
                notice_id=notice_id,
            )
            # delete는 값이 없어도 항상 실행돼야 하므로(예전 값 정리),
            # target_type이 falsy여도 replace_notice_target_type을
            # 무조건 호출한다. 기업마당은 지원지역 필드가 확인되지
            # 않아 notice_region은 호출하지 않는다.
            await replace_notice_target_type(
                session, notice_id, _split_multi_value(item.get("trgetNm"))
            )

            # 기업마당·K-Startup에 같은 사업이 각자 다른 external_id로
            # 중복 등록되는 경우, 제목이 같으면 기업마당을 우선한다.
            # K-Startup을 먼저 수집해서 이미 저장돼 있었더라도 여기서
            # 정리한다.
            if title:
                duplicate_id = await find_notice_id_by_source_and_title(
                    session, KSTARTUP_SOURCE_NAME, title
                )
                if duplicate_id is not None:
                    logger.info(
                        "기업마당 우선 정책으로 K-Startup 중복 공고 삭제: %r", title
                    )
                    await delete_notice(session, duplicate_id)
    except Exception:
        # 이 항목만 SAVEPOINT 단위로 롤백되고, 나머지 항목 처리와
        # 페이지 전체 커밋은 영향받지 않는다. 컬럼 길이 초과 같은
        # 개별 데이터 문제로 페이지 전체가 날아가는 것을 막기 위함.
        logger.exception("기업마당 공고 저장 실패 (external_id=%s)", external_id)
        collection_result.failed_count += 1
        collection_result.failed_ids.append(external_id)
        return

    collection_result.saved_count += 1


async def collect_bizinfo_notices(
    session: AsyncSession, page: int = 1
) -> CollectionResult:
    """기업마당 공고를 한 페이지 수집하고 성공·실패 결과를 반환한다.

    external_id가 없어 건너뛴 항목은 성공·실패 건수에서 제외한다.
    """
    source = await get_or_create_source(
        session,
        source_name=BIZINFO_SOURCE_NAME,
        base_url="https://www.bizinfo.go.kr",
        collect_type="API",
    )
    items = await fetch_bizinfo_notices(page=page)

    collection_result = CollectionResult()
    for item in items:
        await _process_bizinfo_item(session, source.id, item, collection_result)

    await session.commit()
    return collection_result


async def collect_all_bizinfo_notices(session: AsyncSession) -> CollectionResult:
    """기업마당 공고를 첫 페이지부터 끝까지 전부 수집한다.

    빈 페이지가 나오면 끝으로 간주한다 (page=9999처럼 끝을 넘어가도
    에러 없이 빈 리스트를 주는 것을 실제 호출로 확인함). 페이지마다
    커밋해서 트랜잭션이 지나치게 커지는 것을 막는다.
    """
    source = await get_or_create_source(
        session,
        source_name=BIZINFO_SOURCE_NAME,
        base_url="https://www.bizinfo.go.kr",
        collect_type="API",
    )

    collection_result = CollectionResult()
    page = 1
    while True:
        items = await fetch_bizinfo_notices(page=page)
        if not items:
            break

        for item in items:
            await _process_bizinfo_item(session, source.id, item, collection_result)
        await session.commit()

        logger.info(
            "기업마당 페이지 %d 처리 완료 (누적 saved=%d, failed=%d)",
            page,
            collection_result.saved_count,
            collection_result.failed_count,
        )
        page += 1

    return collection_result


async def _process_kstartup_item(
    session: AsyncSession,
    source_id: int,
    item: dict,
    collection_result: CollectionResult,
) -> None:
    """K-Startup 공고 한 건을 처리해 collection_result에 결과를 반영한다."""
    if not isinstance(item, dict):
        return
    pbanc_sn = item.get("pbanc_sn")
    if not pbanc_sn:
        return
    external_id = str(pbanc_sn)

    # 기업마당·K-Startup에 같은 사업이 각자 다른 external_id로 중복
    # 등록되는 경우, 제목이 같으면 기업마당을 우선한다. 기업마당이
    # 이미 수집돼 있으면 이 K-Startup 항목은 저장하지 않는다.
    title = item.get("biz_pbanc_nm")
    if title:
        duplicate_id = await find_notice_id_by_source_and_title(
            session, BIZINFO_SOURCE_NAME, title
        )
        if duplicate_id is not None:
            logger.info("기업마당 우선 정책으로 K-Startup 중복 공고 건너뜀: %r", title)
            return

    try:
        async with session.begin_nested():
            start_date = _parse_kstartup_date(item.get("pbanc_rcpt_bgng_dt"))
            end_date = _parse_kstartup_date(item.get("pbanc_rcpt_end_dt"))
            rcrt_prgs_yn = item.get("rcrt_prgs_yn")
            if rcrt_prgs_yn == "Y":
                status, is_actionable = "모집중", True
            elif rcrt_prgs_yn == "N":
                status, is_actionable = "마감", False
            else:
                # 값이 없거나 Y/N이 아닌 경우 마감으로 단정하지 않는다.
                status, is_actionable = "확인필요", False
            apply_url = item.get("biz_aply_url") or item.get("aply_mthd_onli_rcpt_istc")

            organization_id = None
            organization_name = item.get("sprv_inst")
            if organization_name:
                organization = await get_or_create_organization(
                    session, organization_name
                )
                organization_id = organization.id

            # intg_pbanc_yn(통합공고여부)이 "Y"면 intg_pbanc_biz_nm(통합공고
            # 사업명)이 재공고/연장공고를 묶는 상위 이름 역할을 한다. 이
            # 값을 notice_group_key로 써서 같은 통합공고 아래 공고들을
            # 묶는다.
            notice_group_key = None
            if item.get("intg_pbanc_yn") == "Y":
                notice_group_key = item.get("intg_pbanc_biz_nm")

            notice_id = await upsert_notice(
                session,
                source_id=source_id,
                external_id=external_id,
                title=title,
                organization_id=organization_id,
                notice_group_key=notice_group_key,
                application_start_date=start_date,
                application_end_date=end_date,
                status=status,
                is_actionable=is_actionable,
                source_url=item.get("detl_pg_url"),
                apply_url=apply_url,
                summary_text=item.get("pbanc_ctnt"),
            )
            await save_raw(
                session,
                KstartupRaw,
                key=external_id,
                field=json.dumps(item, ensure_ascii=False),
                notice_id=notice_id,
            )

            # delete는 값이 없어도 항상 실행돼야 하므로(예전 값 정리),
            # 값이 falsy여도 무조건 호출한다.
            await replace_notice_target_type(
                session, notice_id, _split_multi_value(item.get("aply_trgt"))
            )
            await replace_notice_region(
                session, notice_id, _parse_regions(item.get("supt_regin"))
            )
    except Exception:
        logger.exception("K-Startup 공고 저장 실패 (external_id=%s)", external_id)
        collection_result.failed_count += 1
        collection_result.failed_ids.append(external_id)
        return

    collection_result.saved_count += 1


async def collect_kstartup_notices(
    session: AsyncSession, page: int = 1
) -> CollectionResult:
    """K-Startup 공고를 한 페이지 수집하고 성공·실패 결과를 반환한다.

    pbanc_sn이 없어 건너뛴 항목은 성공·실패 건수에서 제외한다.
    """
    source = await get_or_create_source(
        session,
        source_name=KSTARTUP_SOURCE_NAME,
        base_url="https://www.k-startup.go.kr",
        collect_type="API",
    )
    items = await fetch_kstartup_notices(page=page)

    collection_result = CollectionResult()
    for item in items:
        await _process_kstartup_item(session, source.id, item, collection_result)

    await session.commit()
    return collection_result


async def collect_all_kstartup_notices(session: AsyncSession) -> CollectionResult:
    """K-Startup 공고를 첫 페이지부터 끝까지 전부 수집한다.

    K-Startup은 전체가 29,000건 이상이라 페이지 수가 많다(perPage=100
    기준 약 290페이지). 빈 페이지가 나오면 끝으로 간주하고, 페이지마다
    커밋한다 (collect_all_bizinfo_notices와 동일한 이유).
    """
    source = await get_or_create_source(
        session,
        source_name=KSTARTUP_SOURCE_NAME,
        base_url="https://www.k-startup.go.kr",
        collect_type="API",
    )

    collection_result = CollectionResult()
    page = 1
    while True:
        items = await fetch_kstartup_notices(page=page)
        if not items:
            break

        for item in items:
            await _process_kstartup_item(session, source.id, item, collection_result)
        await session.commit()

        logger.info(
            "K-Startup 페이지 %d 처리 완료 (누적 saved=%d, failed=%d)",
            page,
            collection_result.saved_count,
            collection_result.failed_count,
        )
        page += 1

    return collection_result
