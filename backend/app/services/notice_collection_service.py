import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.crawler.bizinfo_client import fetch_bizinfo_notice_by_id, fetch_bizinfo_notices
from app.crawler.kstartup_attachment_client import fetch_kstartup_attachments
from app.crawler.kstartup_client import fetch_kstartup_notices
from app.crawler.msit_client import fetch_msit_notices
from app.models.category import CategoryName
from app.models.raw import BizinfoRaw, KstartupRaw
from app.repositories.notice_repository import (
    delete_notice,
    find_notice_ids_by_source_and_title,
    find_notice_ids_by_source_title_and_dates,
    get_bizinfo_notices_with_raw,
    get_category_mapping,
    get_kg_category_id,
    get_kstartup_notices_with_raw,
    get_max_bizinfo_registration_time,
    get_max_notice_external_id,
    get_notice_business_years,
    get_notice_detail,
    get_notice_region_codes,
    get_notice_regions,
    get_notices_for_status_refresh,
    get_notices_missing_category,
    get_or_create_organization,
    get_or_create_source,
    prune_stale_attachments,
    replace_notice_region,
    replace_notice_target_type,
    save_attachment,
    save_raw,
    set_notice_business_years,
    set_notice_category,
    update_notice_status,
    upsert_notice,
)
from app.services.notice_business_years import parse_biz_enyy

logger = logging.getLogger(__name__)

BIZINFO_SOURCE_NAME = "기업마당"
KSTARTUP_SOURCE_NAME = "K-Startup"
MSIT_SOURCE_NAME = "과학기술정보통신부"


class NoticeRecollectionError(Exception):
    """공고 단건 재수집 실패에 대한 기본 예외."""


class NoticeRecollectionNotFoundError(NoticeRecollectionError):
    """대상 공고를 찾을 수 없거나(잘못된 notice_id), 원본 API에서 더 이상
    조회되지 않을 때(삭제·비공개 전환 등) 발생."""


class UnsupportedRecollectionSourceError(NoticeRecollectionError):
    """단건 재수집을 지원하지 않는 출처에 대해 시도했을 때 발생."""


# 코드는 행정표준코드 기준(2026-07-10 강원/전북 오류 정정 완료).
# TODO: "전남광주(통합특별시)"의 코드 "90"은 임시값 — code.go.kr 공식 코드로 교체 필요.
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
    "강원": "42",
    "강원특별자치도": "42",
    "충북": "43",
    "충청북도": "43",
    "충남": "44",
    "충청남도": "44",
    "전북": "45",
    "전북특별자치도": "45",
    "전남": "46",
    "전라남도": "46",
    "경북": "47",
    "경상북도": "47",
    "경남": "48",
    "경상남도": "48",
    "제주": "50",
    "제주특별자치도": "50",
    "전남광주": "90",  # TODO: 임시값, 실제 행정표준코드로 교체 필요
    "전남광주통합특별시": "90",  # TODO: 임시값, 실제 행정표준코드로 교체 필요
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


def _parse_bizinfo_datetime(value: str | None) -> datetime | None:
    """ "2026-07-09 15:16:31" 형식의 등록시각(creatPnttm)을 datetime으로 변환한다."""
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        logger.warning("기업마당 등록시각 형식을 해석하지 못했습니다: %r", value)
        return None


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


# 기업마당은 "전국" 태그 대신 광역자치단체를 전부 나열하는 방식으로 표현한다.
# 전남·광주 통합(2026-07-01) 전후로 구성이 다를 수 있어(17개/16개) 둘 다 인정한다.
_JEONNAM_CODE = REGION_CODE_BY_NAME["전남"]
_GWANGJU_CODE = REGION_CODE_BY_NAME["광주"]
_JEONNAM_GWANGJU_CODE = REGION_CODE_BY_NAME["전남광주통합특별시"]

_UNCHANGED_REGION_CODES = frozenset(
    code
    for code in REGION_CODE_BY_NAME.values()
    if code not in {"ALL", _JEONNAM_CODE, _GWANGJU_CODE, _JEONNAM_GWANGJU_CODE}
)
_ALL_REGION_CODES_LEGACY = _UNCHANGED_REGION_CODES | {_JEONNAM_CODE, _GWANGJU_CODE}
_ALL_REGION_CODES_CURRENT = _UNCHANGED_REGION_CODES | {_JEONNAM_GWANGJU_CODE}


def _parse_bizinfo_regions(hashtags: str | None) -> list[tuple[str, str]]:
    """기업마당 hashtags 필드에서 지역명과 일치하는 태그만 골라낸다.

    지역명이 다른 주제 태그와 뒤섞여 있어, 일치하지 않는 태그는 경고 없이 무시한다.
    """
    regions: list[tuple[str, str]] = []
    seen_codes: set[str] = set()
    for tag in _split_multi_value(hashtags):
        region_code = REGION_CODE_BY_NAME.get(tag)
        if region_code is None or region_code in seen_codes:
            continue
        seen_codes.add(region_code)
        regions.append((region_code, tag))
    if "ALL" not in seen_codes and (
        _ALL_REGION_CODES_LEGACY <= seen_codes
        or _ALL_REGION_CODES_CURRENT <= seen_codes
    ):
        regions.append(("ALL", "전국"))
    return regions


def _file_type_from_name(file_name: str) -> str | None:
    """파일명 확장자를 대문자로 뽑는다 (확장자 없으면 None)."""
    if "." not in file_name:
        return None
    return file_name.rsplit(".", 1)[-1].upper()


def _parse_bizinfo_attachments(item: dict) -> list[tuple[str, str]]:
    """기업마당 응답에 이미 들어있는 첨부파일 (파일명, URL) 목록을 뽑는다.

    첨부파일이 여러 개면 fileNm/flpthNm이 "@"로 이어붙은 문자열로 오므로 나눠서 짝짓는다.
    """
    attachments: list[tuple[str, str]] = []
    seen_urls: set[str] = set()
    for names_field, urls_field in (
        (item.get("fileNm"), item.get("flpthNm")),
        (item.get("printFileNm"), item.get("printFlpthNm")),
    ):
        if not names_field or not urls_field:
            continue
        names = names_field.split("@")
        urls = urls_field.split("@")
        if len(names) != len(urls):
            logger.warning(
                "기업마당 첨부파일명/URL 개수가 서로 다릅니다: names=%r urls=%r",
                names_field,
                urls_field,
            )
            continue
        for file_name, file_url in zip(names, urls):
            file_name, file_url = file_name.strip(), file_url.strip()
            if not file_name or not file_url or file_url in seen_urls:
                continue
            seen_urls.add(file_url)
            attachments.append((file_name, file_url))
    return attachments


# 실측(기업마당 1,439건 중 날짜 형식 아닌 787건의 92%)으로 확인: 이 표현들은
# 날짜가 없는 게 아니라 "상시모집" 등 종료일 없이 계속 열려있다는 뜻이다.
_ROLLING_OPEN_KEYWORDS = (
    "예산 소진",
    "상시",
    "선착순",
    "수시",
    "연중",
)


def _is_rolling_open(value: str | None) -> bool:
    """정해진 종료일 없이 계속 신청 가능하다는 뜻의 표현인지 확인한다."""
    if not value:
        return False
    return any(keyword in value for keyword in _ROLLING_OPEN_KEYWORDS)


# "모집 완료"류는 반대로 이미 끝났다는 뜻이라 _ROLLING_OPEN_KEYWORDS와 분리했다
# (같이 두면 마감된 공고가 모집중으로 잘못 분류되는 버그가 있었음).
_CLOSED_KEYWORDS = (
    "모집 완료",
    "모집완료",
    "모집 마감",
    "모집마감",
    "모집규모 충족",
    "모집규모충족",
)


def _is_closed_by_keyword(value: str | None) -> bool:
    """정원 충족/모집 마감 공지 등, 이미 모집이 끝났다는 뜻의 표현인지 확인한다."""
    if not value:
        return False
    return any(keyword in value for keyword in _CLOSED_KEYWORDS)


def _within_collection_window(start_date: date | None) -> bool:
    """올해·작년 공고만 수집 대상으로 삼는다 (그 이전 데이터는 저장하지 않음).

    시작일을 못 구한 공고는 "오래된 것"과 구분할 수 없어 일단 수집 대상으로 둔다.
    """
    if start_date is None:
        return True
    return start_date.year >= date.today().year - 1


# 통합 카테고리 "자금"에 매핑되는 원본 카테고리 값(docs/notice-category-mapping.md).
# 지금은 자금만 수집하기로 해서 나머지 카테고리는 저장하지 않는다.
_BIZINFO_FUND_LCLAS = "금융"
_KSTARTUP_FUND_CLSFC = {"정책자금", "융자ㆍ보증", "사업화"}


def _is_bizinfo_fund_category(item: dict) -> bool:
    """기업마당 대분류가 "자금" 카테고리(금융)인지 확인한다."""
    return item.get("pldirSportRealmLclasCodeNm") == _BIZINFO_FUND_LCLAS


def _is_kstartup_fund_category(item: dict) -> bool:
    """K-Startup 분류가 "자금" 카테고리(정책자금/융자보증/사업화)인지 확인한다."""
    return item.get("supt_biz_clsfc") in _KSTARTUP_FUND_CLSFC


def _bizinfo_raw_category_key(item: dict) -> str | None:
    """category_mapping.raw_category와 매칭되는 키를 만든다.

    기업마당은 대분류 기준이 원칙이지만 "경영"만 중분류까지 붙여야 한다.
    """
    lclas = item.get("pldirSportRealmLclasCodeNm")
    if not lclas:
        return None
    if lclas == "경영":
        mlsfc = item.get("pldirSportRealmMlsfcCodeNm")
        if not mlsfc:
            return None
        return f"BIZINFO:경영:{mlsfc}"
    return f"BIZINFO:{lclas}"


def _kstartup_raw_category_key(item: dict) -> str | None:
    """category_mapping.raw_category와 매칭되는 키(KSTARTUP:분류)를 만든다."""
    clsfc = item.get("supt_biz_clsfc")
    if not clsfc:
        return None
    return f"KSTARTUP:{clsfc}"


def _derive_status_from_dates(
    start_date: date | None, end_date: date | None, raw_period: str | None = None
) -> tuple[str, bool]:
    """기업마당 모집 상태를 신청 시작일과 종료일 기준으로 추정한다.

    날짜로 판단 안 되면 raw_period의 마감/상시모집 키워드로 보조 판정한다.
    """
    today = date.today()
    if start_date is not None and start_date > today:
        return "예정", False
    if end_date is not None and end_date < today:
        return "마감", False
    if start_date is not None and end_date is not None:
        return "모집중", True
    if _is_closed_by_keyword(raw_period):
        return "마감", False
    if _is_rolling_open(raw_period):
        return "모집중", True
    return "확인필요", False


async def _find_cross_source_duplicate_notice_ids(
    session: AsyncSession,
    source_name: str,
    title: str,
    start_date: date | None,
    end_date: date | None,
) -> list[int]:
    """기업마당·K-Startup 교차 중복 판정을 2단계로 한다.

    제목 후보 1건이면 그대로 확정, 2건 이상이면 신청기간까지 일치해야 매칭한다
    (기업마당 89%가 상시모집이라 날짜를 무조건 요구하면 대부분 매칭이 안 됐음).
    """
    candidates = await find_notice_ids_by_source_and_title(session, source_name, title)
    if len(candidates) <= 1:
        return candidates
    if start_date is None or end_date is None:
        return []
    return await find_notice_ids_by_source_title_and_dates(
        session, source_name, title, start_date, end_date
    )


async def _process_bizinfo_item(
    session: AsyncSession,
    source_id: int,
    item: dict,
    collection_result: CollectionResult,
    category_mapping: dict[str, int],
) -> None:
    """기업마당 공고 한 건을 처리해 collection_result에 결과를 반영한다."""
    if not isinstance(item, dict):
        return
    pblanc_id = item.get("pblancId")
    if not pblanc_id:
        return
    if not _is_bizinfo_fund_category(item):
        return
    external_id = str(pblanc_id)

    try:
        async with session.begin_nested():
            raw_period = item.get("reqstBeginEndDe")
            start_date, end_date = _parse_bizinfo_date_range(raw_period)
            if not _within_collection_window(start_date):
                return
            status, is_actionable = _derive_status_from_dates(
                start_date, end_date, raw_period
            )

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
                notice_group_key=None,  # 기업마당은 재공고/연장공고 필드가 없어 비워둠
                category_id=category_mapping.get(_bizinfo_raw_category_key(item)),
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
            # delete는 값이 없어도 예전 값 정리를 위해 항상 실행돼야 한다.
            await replace_notice_target_type(
                session, notice_id, _split_multi_value(item.get("trgetNm"))
            )
            await replace_notice_region(
                session, notice_id, _parse_bizinfo_regions(item.get("hashtags"))
            )
            bizinfo_attachments = _parse_bizinfo_attachments(item)
            for file_name, file_url in bizinfo_attachments:
                await save_attachment(
                    session,
                    notice_id,
                    file_name,
                    file_url,
                    _file_type_from_name(file_name),
                )
            # 기업마당 응답엔 항상 첨부파일 전체 목록이 실려오므로, 이번에
            # 없는 URL은 원본에서 사라진(교체·삭제) 첨부파일로 보고 정리한다.
            await prune_stale_attachments(
                session, notice_id, {url for _, url in bizinfo_attachments}
            )

            # 기업마당·K-Startup 중복 등록 시 기업마당을 우선해 K-Startup
            # 쪽을 정리한다 (판정 기준은 _find_cross_source_duplicate_notice_ids).
            if title:
                duplicate_ids = await _find_cross_source_duplicate_notice_ids(
                    session, KSTARTUP_SOURCE_NAME, title, start_date, end_date
                )
                for duplicate_id in duplicate_ids:
                    logger.info(
                        "기업마당 우선 정책으로 K-Startup 중복 공고 삭제: %r", title
                    )
                    await delete_notice(session, duplicate_id)
    except Exception:
        # 이 항목만 SAVEPOINT 단위로 롤백되어 나머지 항목·페이지 커밋엔 영향 없다.
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
    category_mapping = await get_category_mapping(session)
    items = await fetch_bizinfo_notices(page=page)

    collection_result = CollectionResult()
    for item in items:
        await _process_bizinfo_item(
            session, source.id, item, collection_result, category_mapping
        )

    await session.commit()
    return collection_result


async def recollect_bizinfo_notice(session: AsyncSession, notice_id: int) -> None:
    """이미 저장된 기업마당 공고 하나만 원본 API에서 다시 가져와 갱신한다.

    K-Startup은 pbanc_sn 필터가 무시돼 단건 조회가 불가능해 기업마당만 지원한다.
    """
    row = await get_notice_detail(session, notice_id)
    if row is None:
        raise NoticeRecollectionNotFoundError(
            f"notice_id {notice_id}를 찾을 수 없습니다."
        )
    notice, source_name, _ = row
    if source_name != BIZINFO_SOURCE_NAME:
        raise UnsupportedRecollectionSourceError(
            f"{source_name}은 단건 재수집을 지원하지 않습니다 (기업마당만 지원)."
        )

    item = await fetch_bizinfo_notice_by_id(notice.external_id)
    if item is None:
        raise NoticeRecollectionNotFoundError(
            "기업마당에서 해당 공고를 더 이상 찾을 수 없습니다 "
            "(비공개 전환되었거나 삭제되었을 수 있습니다)."
        )

    category_mapping = await get_category_mapping(session)
    collection_result = CollectionResult()
    await _process_bizinfo_item(
        session, notice.source_id, item, collection_result, category_mapping
    )
    await session.commit()

    # _process_bizinfo_item이 "해당 없음"으로 조용히 리턴하는 경우는 실패가
    # 아니므로 failed_count만 오류로 취급한다.
    if collection_result.failed_count > 0:
        raise NoticeRecollectionError(
            "재수집 처리 중 오류가 발생해 반영하지 못했습니다."
        )


# 기업마당 응답은 creatPnttm(등록시각) 기준 내림차순이 실측 확인됨. ID가
# 먼저 잡히고 공개가 나중인 경우를 놓치지 않도록 여유분을 두고 더 과거까지 본다.
_BIZINFO_EARLY_STOP_BUFFER = timedelta(hours=24)


def _bizinfo_item_before_cutoff(item: dict, stop_before: datetime | None) -> bool:
    """이 항목이 조기종료 기준 시각보다 과거(=이미 확인한 범위)인지 판단한다."""
    if stop_before is None:
        return False
    created_at = _parse_bizinfo_datetime(item.get("creatPnttm"))
    return created_at is not None and created_at <= stop_before


async def collect_all_bizinfo_notices(session: AsyncSession) -> CollectionResult:
    """기업마당 공고를 첫 페이지부터 끝까지 전부 수집한다.

    조기종료: 직전 수집에서 실제 저장된 공고의 등록시각 최댓값 이전을 만나면 멈춘다
    (수집 실패분은 커서에 반영 안 돼 다음 회차에서 다시 시도됨).
    """
    source = await get_or_create_source(
        session,
        source_name=BIZINFO_SOURCE_NAME,
        base_url="https://www.bizinfo.go.kr",
        collect_type="API",
    )
    try:
        # jsonb 캐스팅 쿼리라 유효하지 않은 JSON이 있으면 실패할 수 있어,
        # SAVEPOINT로 감싸 실패해도 이후 페이지 처리·커밋에 영향 없게 한다.
        async with session.begin_nested():
            since = await get_max_bizinfo_registration_time(session, source.id)
    except Exception:
        logger.warning(
            "기업마당 조기종료 커서 계산 실패, 이번 수집은 조기종료 없이 전체를 훑습니다",
            exc_info=True,
        )
        since = None
    stop_before = since - _BIZINFO_EARLY_STOP_BUFFER if since is not None else None
    category_mapping = await get_category_mapping(session)

    collection_result = CollectionResult()
    page = 1
    while True:
        items = await fetch_bizinfo_notices(page=page)
        if not items:
            break

        reached_known_items = False
        for item in items:
            if _bizinfo_item_before_cutoff(item, stop_before):
                reached_known_items = True
                break
            await _process_bizinfo_item(
                session, source.id, item, collection_result, category_mapping
            )
        await session.commit()

        logger.info(
            "기업마당 페이지 %d 처리 완료 (누적 saved=%d, failed=%d)",
            page,
            collection_result.saved_count,
            collection_result.failed_count,
        )

        if reached_known_items:
            logger.info("기업마당 직전 수집 시점(%s) 부근 도달, 조기 종료", stop_before)
            break

        page += 1

    return collection_result


# MSIT API는 신청기간 필드가 없는 게시판형이라 이미 끝난 "~선정결과" 게시물이
# 섞여 온다(실측, 이슈 #104). 날짜로 못 거르니 제목 키워드로 제외한다.
_MSIT_RESULT_KEYWORDS = ("선정결과", "결과")


def _is_msit_result_announcement(subject: str | None) -> bool:
    """제목이 이미 끝난 과제의 결과 발표성 게시물인지 확인한다."""
    if not subject:
        return False
    return any(keyword in subject for keyword in _MSIT_RESULT_KEYWORDS)


def _parse_msit_date(value: str | None) -> date | None:
    """ "2026-07-13" 형식의 게시일(pressDt)을 date로 변환한다."""
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        logger.warning(
            "과학기술정보통신부 게시일 형식을 해석하지 못했습니다: %r", value
        )
        return None


_MSIT_VIEW_URL_ID_PATTERN = re.compile(r"nttSeqNo=(\d+)")


def _extract_msit_external_id(view_url: str | None) -> str | None:
    """상세페이지 URL(viewUrl)의 nttSeqNo를 고유 id로 쓴다.

    이 API 응답에는 별도 게시물 id 필드가 없어, 게시물마다 고유한 nttSeqNo로 대신한다.
    """
    if not view_url:
        return None
    match = _MSIT_VIEW_URL_ID_PATTERN.search(view_url)
    return match.group(1) if match else None


async def _process_msit_item(
    session: AsyncSession,
    source_id: int,
    item: dict,
    collection_result: CollectionResult,
    category_id: int | None,
) -> None:
    """과학기술정보통신부 사업공고 한 건을 처리해 collection_result에 결과를 반영한다."""
    if not isinstance(item, dict):
        return
    subject = item.get("subject")
    view_url = item.get("viewUrl")
    external_id = _extract_msit_external_id(view_url)
    if not external_id:
        logger.warning(
            "과학기술정보통신부 게시물 id를 추출하지 못했습니다: %r", view_url
        )
        return
    if _is_msit_result_announcement(subject):
        return

    press_date = _parse_msit_date(item.get("pressDt"))
    if not _within_collection_window(press_date):
        return

    try:
        async with session.begin_nested():
            organization = await get_or_create_organization(session, MSIT_SOURCE_NAME)

            # 신청기간 필드가 없어 날짜로 상태 판단이 안 되므로, 결과 발표성
            # 게시물이 걸러진 나머지는 열려있는 것으로 간주한다.
            notice_id = await upsert_notice(
                session,
                source_id=source_id,
                external_id=external_id,
                title=subject,
                organization_id=organization.id,
                notice_group_key=None,
                category_id=category_id,
                application_start_date=None,
                application_end_date=None,
                status="모집중",
                is_actionable=True,
                source_url=view_url,
                apply_url=view_url,
                summary_text=None,
            )

            msit_attachments = [
                (f.get("fileName"), f.get("fileUrl"))
                for f in item.get("files") or []
                if f.get("fileName") and f.get("fileUrl")
            ]
            for file_name, file_url in msit_attachments:
                await save_attachment(
                    session,
                    notice_id,
                    file_name,
                    file_url,
                    _file_type_from_name(file_name),
                )
            await prune_stale_attachments(
                session, notice_id, {url for _, url in msit_attachments}
            )
    except Exception:
        logger.exception(
            "과학기술정보통신부 공고 저장 실패 (external_id=%s)", external_id
        )
        collection_result.failed_count += 1
        collection_result.failed_ids.append(external_id)
        return

    collection_result.saved_count += 1


async def collect_all_msit_notices(session: AsyncSession) -> CollectionResult:
    """과학기술정보통신부 사업공고를 첫 페이지부터 올해~작년치까지 수집한다.

    등록시각 기준 커서 대신, 응답이 최신순이라는 전제 하에 게시일이 수집
    기간 밖인 항목을 만나면 그 페이지에서 멈춘다.
    """
    source = await get_or_create_source(
        session,
        source_name=MSIT_SOURCE_NAME,
        base_url="https://www.msit.go.kr",
        collect_type="API",
    )
    category_id = await get_kg_category_id(session, CategoryName.TECH)
    if category_id is None:
        logger.error(
            "kg_category에 'R&D·기술'이 없어 과학기술정보통신부 수집을 건너뜁니다"
        )
        return CollectionResult()

    collection_result = CollectionResult()
    page = 1
    while True:
        items = await fetch_msit_notices(page=page)
        if not items:
            break

        reached_old_items = any(
            not _within_collection_window(_parse_msit_date(item.get("pressDt")))
            for item in items
        )
        for item in items:
            await _process_msit_item(
                session, source.id, item, collection_result, category_id
            )
        await session.commit()

        logger.info(
            "과학기술정보통신부 페이지 %d 처리 완료 (누적 saved=%d, failed=%d)",
            page,
            collection_result.saved_count,
            collection_result.failed_count,
        )

        if reached_old_items:
            logger.info(
                "과학기술정보통신부 수집 기간(올해~작년) 밖 항목 도달, 조기 종료"
            )
            break

        page += 1

    return collection_result


async def _save_kstartup_attachments(
    session: AsyncSession, notice_id: int, pbanc_sn: str
) -> None:
    """K-Startup 상세페이지를 크롤링해 첨부파일 메타데이터만 저장한다.

    현재 수집 파이프라인에서는 호출하지 않는다 — 무거운 상세페이지 크롤링이라
    매칭 후보로 좁혀진 공고에 대해서만 2차 필터링 단계에서 쓰는 용도로 남겨둔다.
    """
    try:
        attachments = await fetch_kstartup_attachments(int(pbanc_sn))
    except Exception:
        logger.exception("K-Startup 첨부파일 조회 실패 (notice_id=%s)", notice_id)
        return

    try:
        async with session.begin_nested():
            for file_name, file_url in attachments:
                await save_attachment(
                    session,
                    notice_id,
                    file_name,
                    file_url,
                    _file_type_from_name(file_name),
                )
    except Exception:
        logger.exception("K-Startup 첨부파일 저장 실패 (notice_id=%s)", notice_id)


async def _process_kstartup_item(
    session: AsyncSession,
    source_id: int,
    item: dict,
    collection_result: CollectionResult,
    category_mapping: dict[str, int],
) -> None:
    """K-Startup 공고 한 건을 처리해 collection_result에 결과를 반영한다."""
    if not isinstance(item, dict):
        return
    pbanc_sn = item.get("pbanc_sn")
    if not pbanc_sn:
        return
    if not _is_kstartup_fund_category(item):
        return
    external_id = str(pbanc_sn)

    start_date = _parse_kstartup_date(item.get("pbanc_rcpt_bgng_dt"))
    if not _within_collection_window(start_date):
        return
    end_date = _parse_kstartup_date(item.get("pbanc_rcpt_end_dt"))

    # 기업마당·K-Startup 중복 등록 시 기업마당을 우선해 이 K-Startup 항목은
    # 저장하지 않는다 (판정 기준은 _find_cross_source_duplicate_notice_ids).
    title = item.get("biz_pbanc_nm")
    if title:
        duplicate_ids = await _find_cross_source_duplicate_notice_ids(
            session, BIZINFO_SOURCE_NAME, title, start_date, end_date
        )
        if duplicate_ids:
            logger.info("기업마당 우선 정책으로 K-Startup 중복 공고 건너뜀: %r", title)
            return

    try:
        async with session.begin_nested():
            rcrt_prgs_yn = item.get("rcrt_prgs_yn")
            if rcrt_prgs_yn == "Y":
                status, is_actionable = "모집중", True
            elif rcrt_prgs_yn == "N":
                status, is_actionable = "마감", False
            else:
                status, is_actionable = (
                    "확인필요",
                    False,
                )  # Y/N 아니면 마감으로 단정 안 함
            apply_url = item.get("biz_aply_url") or item.get("aply_mthd_onli_rcpt_istc")

            organization_id = None
            organization_name = item.get("sprv_inst")
            if organization_name:
                organization = await get_or_create_organization(
                    session, organization_name
                )
                organization_id = organization.id

            # intg_pbanc_yn(통합공고여부)="Y"면 intg_pbanc_biz_nm이 재공고/연장공고를
            # 묶는 상위 이름 역할을 하므로 notice_group_key로 쓴다.
            notice_group_key = None
            if item.get("intg_pbanc_yn") == "Y":
                notice_group_key = item.get("intg_pbanc_biz_nm")

            # 업력 축(1차 필터)용으로 biz_enyy를 구조화해 컬럼에 저장한다.
            # 제한 정보가 없으면(None) 두 컬럼 모두 NULL로 둔다(permissive).
            parsed_years = parse_biz_enyy(item.get("biz_enyy"))
            allows_prestartup, max_years = parsed_years or (None, None)

            notice_id = await upsert_notice(
                session,
                source_id=source_id,
                external_id=external_id,
                title=title,
                organization_id=organization_id,
                notice_group_key=notice_group_key,
                category_id=category_mapping.get(_kstartup_raw_category_key(item)),
                application_start_date=start_date,
                application_end_date=end_date,
                status=status,
                is_actionable=is_actionable,
                source_url=item.get("detl_pg_url"),
                apply_url=apply_url,
                summary_text=item.get("pbanc_ctnt"),
                target_business_years_max=max_years,
                target_allows_prestartup=allows_prestartup,
            )
            await save_raw(
                session,
                KstartupRaw,
                key=external_id,
                field=json.dumps(item, ensure_ascii=False),
                notice_id=notice_id,
            )

            # delete는 값이 없어도 예전 값 정리를 위해 항상 실행돼야 한다.
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
    category_mapping = await get_category_mapping(session)
    items = await fetch_kstartup_notices(page=page)

    collection_result = CollectionResult()
    for item in items:
        await _process_kstartup_item(
            session, source.id, item, collection_result, category_mapping
        )

    await session.commit()
    return collection_result


# K-Startup은 등록시각 필드가 없어 순서가 보장되는 pbanc_sn(일련번호)을
# 커서로 쓴다. 채번과 공개 시점이 어긋날 수 있어 여유분을 둔다(실측 확인).
_KSTARTUP_EARLY_STOP_BUFFER = 200


def _kstartup_item_before_cutoff(item: dict, stop_below: int | None) -> bool:
    """이 항목이 조기종료 기준 pbanc_sn보다 작은(=이미 확인한 범위) 항목인지 판단한다."""
    if stop_below is None:
        return False
    pbanc_sn = item.get("pbanc_sn")
    return isinstance(pbanc_sn, int) and pbanc_sn <= stop_below


async def collect_all_kstartup_notices(session: AsyncSession) -> CollectionResult:
    """K-Startup 공고를 첫 페이지부터 끝까지 전부 수집한다.

    전체 29,000건 이상이라 페이지가 많다(perPage=100 기준 약 290페이지).
    조기종료 기준은 _KSTARTUP_EARLY_STOP_BUFFER 참고.
    """
    source = await get_or_create_source(
        session,
        source_name=KSTARTUP_SOURCE_NAME,
        base_url="https://www.k-startup.go.kr",
        collect_type="API",
    )
    try:
        # external_id를 정수로 캐스팅하는 쿼리라 숫자가 아닌 값이 섞이면
        # 실패할 수 있어, SAVEPOINT로 감싸 트랜잭션 전체가 막히지 않게 한다.
        async with session.begin_nested():
            max_saved_id = await get_max_notice_external_id(session, source.id)
    except Exception:
        logger.warning(
            "K-Startup 조기종료 커서 계산 실패, 이번 수집은 조기종료 없이 전체를 훑습니다",
            exc_info=True,
        )
        max_saved_id = None
    stop_below = (
        max_saved_id - _KSTARTUP_EARLY_STOP_BUFFER if max_saved_id is not None else None
    )
    category_mapping = await get_category_mapping(session)

    collection_result = CollectionResult()
    page = 1
    while True:
        items = await fetch_kstartup_notices(page=page)
        if not items:
            break

        reached_known_items = False
        for item in items:
            if _kstartup_item_before_cutoff(item, stop_below):
                reached_known_items = True
                break
            await _process_kstartup_item(
                session, source.id, item, collection_result, category_mapping
            )
        await session.commit()

        logger.info(
            "K-Startup 페이지 %d 처리 완료 (누적 saved=%d, failed=%d)",
            page,
            collection_result.saved_count,
            collection_result.failed_count,
        )

        if reached_known_items:
            logger.info("K-Startup 직전 수집 지점(%s) 부근 도달, 조기 종료", stop_below)
            break

        page += 1

    return collection_result


async def backfill_notice_categories(session: AsyncSession) -> dict[str, int]:
    """category_id가 비어있는 기존 공고를 채운다 (일회성 보정).

    외부 API를 다시 호출하지 않고, 저장해둔 원본 응답만으로 category_mapping과 대조한다.
    """
    category_mapping = await get_category_mapping(session)
    checked = 0
    updated = 0

    for raw_model_cls, raw_category_key in (
        (BizinfoRaw, _bizinfo_raw_category_key),
        (KstartupRaw, _kstartup_raw_category_key),
    ):
        rows = await get_notices_missing_category(session, raw_model_cls)
        for notice_id, raw_field in rows:
            checked += 1
            # raw_field가 NULL이거나 손상됐어도 이 건만 건너뛰고 나머지
            # 수천 건 백필은 계속되게 한다.
            try:
                item = json.loads(raw_field)
            except (TypeError, json.JSONDecodeError):
                logger.warning(
                    "category 백필 중 raw 데이터를 파싱하지 못했습니다 "
                    "(notice_id=%s, raw_model=%s)",
                    notice_id,
                    raw_model_cls.__tablename__,
                )
                continue
            category_id = category_mapping.get(raw_category_key(item))
            if category_id is not None:
                await set_notice_category(session, notice_id, category_id)
                updated += 1

    await session.commit()
    return {"checked": checked, "updated": updated}


async def refresh_notice_statuses(session: AsyncSession) -> dict[str, int]:
    """마감일이 지났는데 status가 아직 갱신 안 된 공고를 오늘 날짜 기준으로 재계산한다.

    상시모집 판단은 원본 문자열 없이 재현 불가하므로, 재계산이 "확인필요"인데
    기존이 "모집중"이면 건드리지 않는다(상시모집 공고 오탐 마감 방지).
    """
    checked = 0
    updated = 0

    rows = await get_notices_for_status_refresh(session)
    for notice_id, start_date, end_date, current_status in rows:
        checked += 1
        new_status, new_is_actionable = _derive_status_from_dates(start_date, end_date)
        if new_status == "확인필요" and current_status == "모집중":
            continue
        if new_status != current_status:
            await update_notice_status(
                session, notice_id, new_status, new_is_actionable
            )
            updated += 1

    await session.commit()
    return {"checked": checked, "updated": updated}


async def backfill_bizinfo_nationwide_regions(session: AsyncSession) -> dict[str, int]:
    """기업마당 공고 중 hashtags에 광역자치단체 17개가 모두 태그돼 있는데
    아직 region_code=ALL("전국")이 없는 공고에 이를 추가한다.

    조기종료 커서 때문에 일반 재수집으로는 훑이지 않는 기존 공고를 위한 일회성 보정.
    """
    checked = 0
    updated = 0

    rows = await get_bizinfo_notices_with_raw(session)
    for notice_id, raw_field in rows:
        checked += 1
        try:
            item = json.loads(raw_field)
        except (TypeError, json.JSONDecodeError):
            logger.warning(
                "기업마당 전국 지역 백필 중 raw 데이터를 파싱하지 못했습니다 "
                "(notice_id=%s)",
                notice_id,
            )
            continue

        regions = _parse_bizinfo_regions(item.get("hashtags"))
        if not any(region_code == "ALL" for region_code, _ in regions):
            continue

        existing_region_names = await get_notice_regions(session, notice_id)
        if "전국" in existing_region_names:
            continue

        await replace_notice_region(session, notice_id, regions)
        updated += 1

    await session.commit()
    return {"checked": checked, "updated": updated}


async def backfill_notice_region_codes(session: AsyncSession) -> dict[str, int]:
    """저장된 원본 데이터를 다시 읽어 모든 공고의 지역 코드를 최신 기준으로 재계산한다.

    강원/전북 오류 코드 정정과 전남·광주 통합 대응을 위한 일회성 백필(2026-07-10).
    """
    checked = 0
    updated = 0

    bizinfo_rows = await get_bizinfo_notices_with_raw(session)
    for notice_id, raw_field in bizinfo_rows:
        checked += 1
        try:
            item = json.loads(raw_field)
        except (TypeError, json.JSONDecodeError):
            logger.warning(
                "지역 코드 백필 중 기업마당 raw 데이터를 파싱하지 못했습니다 "
                "(notice_id=%s)",
                notice_id,
            )
            continue
        new_regions = _parse_bizinfo_regions(item.get("hashtags"))
        new_codes = {region_code for region_code, _ in new_regions}
        existing_codes = await get_notice_region_codes(session, notice_id)
        if new_codes == existing_codes:
            continue
        await replace_notice_region(session, notice_id, new_regions)
        updated += 1

    kstartup_rows = await get_kstartup_notices_with_raw(session)
    for notice_id, raw_field in kstartup_rows:
        checked += 1
        try:
            item = json.loads(raw_field)
        except (TypeError, json.JSONDecodeError):
            logger.warning(
                "지역 코드 백필 중 K-Startup raw 데이터를 파싱하지 못했습니다 "
                "(notice_id=%s)",
                notice_id,
            )
            continue
        new_regions = _parse_regions(item.get("supt_regin"))
        new_codes = {region_code for region_code, _ in new_regions}
        existing_codes = await get_notice_region_codes(session, notice_id)
        if new_codes == existing_codes:
            continue
        await replace_notice_region(session, notice_id, new_regions)
        updated += 1

    await session.commit()
    return {"checked": checked, "updated": updated}


async def backfill_notice_business_years(session: AsyncSession) -> dict[str, int]:
    """저장된 K-Startup 원본(biz_enyy)을 다시 읽어 업력 구조화 컬럼
    (target_business_years_max, target_allows_prestartup)을 보정한다.

    업력 축(1차 필터)을 위해 컬럼을 새로 도입해, 그 이전에 수집된 공고는
    두 컬럼이 비어 있다. backfill_notice_region_codes와 같은 패턴으로 외부
    API 재호출 없이 저장된 원본만으로 재계산한다. biz_enyy가 없는 bizinfo는
    애초에 대상이 아니라 K-Startup 원본만 훑는다.
    """
    checked = 0
    updated = 0

    kstartup_rows = await get_kstartup_notices_with_raw(session)
    for notice_id, raw_field in kstartup_rows:
        checked += 1
        try:
            item = json.loads(raw_field)
        except (TypeError, json.JSONDecodeError):
            logger.warning(
                "업력 백필 중 K-Startup raw 데이터를 파싱하지 못했습니다 "
                "(notice_id=%s)",
                notice_id,
            )
            continue
        allows_prestartup, max_years = parse_biz_enyy(item.get("biz_enyy")) or (
            None,
            None,
        )
        existing = await get_notice_business_years(session, notice_id)
        if existing == (max_years, allows_prestartup):
            continue
        await set_notice_business_years(
            session, notice_id, max_years, allows_prestartup
        )
        updated += 1

    await session.commit()
    return {"checked": checked, "updated": updated}
