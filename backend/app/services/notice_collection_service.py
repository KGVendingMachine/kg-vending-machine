import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.crawler.bizinfo_client import fetch_bizinfo_notices
from app.crawler.kstartup_attachment_client import fetch_kstartup_attachments
from app.crawler.kstartup_client import fetch_kstartup_notices
from app.models.raw import BizinfoRaw, KstartupRaw
from app.repositories.notice_repository import (
    delete_notice,
    find_notice_id_by_source_and_title,
    get_category_mapping,
    get_max_notice_external_id,
    get_notices_for_status_refresh,
    get_notices_missing_category,
    get_or_create_organization,
    get_or_create_source,
    get_source_updated_at,
    replace_notice_region,
    replace_notice_target_type,
    save_attachment,
    save_raw,
    set_notice_category,
    update_notice_status,
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


def _parse_bizinfo_regions(hashtags: str | None) -> list[tuple[str, str]]:
    """기업마당 hashtags 필드에서 지역명과 일치하는 태그만 골라낸다.

    기업마당 API에는 K-Startup의 supt_regin 같은 전용 지역 필드가 없다.
    대신 hashtags에 지역명이 "경영", "2026", 기관명 같은 다른 주제 태그와
    뒤섞여 들어있다(실제 응답 예: "경영,서울,부산,...,지식재산처"). 알려진
    지역명과 정확히 일치하는 태그만 채택하고 나머지는 조용히 무시한다 —
    지역이 아닌 태그가 대부분이라 _parse_regions처럼 태그마다 경고를
    남기면 로그가 도배된다.
    """
    regions: list[tuple[str, str]] = []
    seen_codes: set[str] = set()
    for tag in _split_multi_value(hashtags):
        region_code = REGION_CODE_BY_NAME.get(tag)
        if region_code is None or region_code in seen_codes:
            continue
        seen_codes.add(region_code)
        regions.append((region_code, tag))
    return regions


def _file_type_from_name(file_name: str) -> str | None:
    if "." not in file_name:
        return None
    return file_name.rsplit(".", 1)[-1].upper()


def _parse_bizinfo_attachments(item: dict) -> list[tuple[str, str]]:
    """기업마당 응답에 이미 들어있는 첨부파일 (파일명, URL) 목록을 뽑는다.

    K-Startup과 달리 기업마당은 목록 API 응답 자체에 첨부파일 URL이 있어
    별도 상세페이지 크롤링이 필요 없다. 다만 첨부파일이 여러 개인 공고는
    fileNm/flpthNm(그리고 printFileNm/printFlpthNm) 각각이 "@"로 이어붙은
    문자열로 온다 — 실제 응답으로 확인함(파일 4개짜리 공고에서 flpthNm이
    "url0@url1@url2@url3" 형태, fileSn만 0/1/2/3으로 다름). 그대로 하나의
    파일명/URL로 저장하면 URL 여러 개가 이어붙은 깨진 값이 되어 다운로드가
    안 되므로, "@" 기준으로 나눠서 같은 순번끼리 짝짓는다.
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


# 기업마당 전체(1,439건) 실제 데이터로 확인함: reqstBeginEndDe가
# "YYYY-MM-DD ~ YYYY-MM-DD" 형식이 아닌 787건 중 726건(약 92%)이
# 날짜가 없는 게 아니라 "상시/예산 소진 시까지" 같은, 정해진 종료일 없이
# 계속 열려있다는 뜻의 표현이었다. 이걸 그냥 "확인필요"로 두면 실제로는
# 신청 가능한 공고 대부분이 "확인필요"로 잘못 분류된다.
_ROLLING_OPEN_KEYWORDS = (
    "예산 소진",
    "상시",
    "선착순",
    "모집 완료",
    "모집완료",
    "모집 마감",
    "모집마감",
    "수시",
    "연중",
    "모집규모 충족",
    "모집규모충족",
)


def _is_rolling_open(value: str | None) -> bool:
    """정해진 종료일 없이 계속 신청 가능하다는 뜻의 표현인지 확인한다."""
    if not value:
        return False
    return any(keyword in value for keyword in _ROLLING_OPEN_KEYWORDS)


def _within_collection_window(start_date: date | None) -> bool:
    """올해·작년 공고만 수집 대상으로 삼는다 (그 이전 데이터는 저장하지 않음).

    신청시작일을 못 구한 공고까지 무조건 버리면 "오래된 공고"와 "API 응답에
    날짜가 아예 없는 경우"를 구분할 수 없어, 시작일을 모르면 일단 수집
    대상으로 둔다.
    """
    if start_date is None:
        return True
    return start_date.year >= date.today().year - 1


# docs/notice-category-mapping.md, category_mapping 시드 데이터(0756e6c105fe) 기준 —
# 통합 카테고리 "자금"에 매핑되는 원본 카테고리 원문 값. 지금은 자금만 수집하기로
# 정해서, 나머지 카테고리(기술/수출·글로벌/인력 등)는 아예 저장하지 않는다.
_BIZINFO_FUND_LCLAS = "금융"
_KSTARTUP_FUND_CLSFC = {"정책자금", "융자ㆍ보증", "사업화"}


def _is_bizinfo_fund_category(item: dict) -> bool:
    return item.get("pldirSportRealmLclasCodeNm") == _BIZINFO_FUND_LCLAS


def _is_kstartup_fund_category(item: dict) -> bool:
    return item.get("supt_biz_clsfc") in _KSTARTUP_FUND_CLSFC


def _bizinfo_raw_category_key(item: dict) -> str | None:
    """category_mapping.raw_category와 매칭되는 키를 만든다.

    기업마당은 대분류 기준이 원칙이지만, "경영"만 중분류까지 붙여야
    한다 (docs/notice-category-mapping.md, 0756e6c105fe 시드 데이터 참고).
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
    clsfc = item.get("supt_biz_clsfc")
    if not clsfc:
        return None
    return f"KSTARTUP:{clsfc}"


def _derive_status_from_dates(
    start_date: date | None, end_date: date | None, raw_period: str | None = None
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
    if _is_rolling_open(raw_period):
        return "모집중", True
    return "확인필요", False


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
                # 기업마당 응답에는 재공고/연장공고를 나타내는 필드가
                # 확인되지 않아 notice_group_key는 비워둔다
                # (K-Startup의 intg_pbanc_yn과 달리 별도 이슈로 조사 필요).
                notice_group_key=None,
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
            # delete는 값이 없어도 항상 실행돼야 하므로(예전 값 정리),
            # 값이 falsy여도 무조건 호출한다. 기업마당은 전용 지역 필드가
            # 없어 hashtags에서 지역명과 일치하는 태그만 추려 사용한다.
            await replace_notice_target_type(
                session, notice_id, _split_multi_value(item.get("trgetNm"))
            )
            await replace_notice_region(
                session, notice_id, _parse_bizinfo_regions(item.get("hashtags"))
            )
            for file_name, file_url in _parse_bizinfo_attachments(item):
                await save_attachment(
                    session,
                    notice_id,
                    file_name,
                    file_url,
                    _file_type_from_name(file_name),
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
    category_mapping = await get_category_mapping(session)
    items = await fetch_bizinfo_notices(page=page)

    collection_result = CollectionResult()
    for item in items:
        await _process_bizinfo_item(
            session, source.id, item, collection_result, category_mapping
        )

    await session.commit()
    return collection_result


# 기업마당 응답은 creatPnttm(등록시각) 기준 최신순으로 오는 것을 실제
# 호출로 확인함(페이지 넘어가도 끊김 없이 내림차순). 조기종료 시 직전
# 수집 시각(notice_source.updated_at) 딱 그 지점에서 멈추면, 시스템
# 내부적으로 ID/시각이 먼저 잡히고 공개는 나중에 되는 경우(관공서
# 시스템에서 흔함) 그 사이에 낀 공고를 영원히 놓칠 수 있다. 여유분을
# 두고 그보다 더 과거까지 다시 확인한다.
_BIZINFO_EARLY_STOP_BUFFER = timedelta(hours=24)


def _bizinfo_item_before_cutoff(item: dict, stop_before: datetime | None) -> bool:
    """이 항목이 조기종료 기준 시각보다 과거(=이미 확인한 범위)인지 판단한다."""
    if stop_before is None:
        return False
    created_at = _parse_bizinfo_datetime(item.get("creatPnttm"))
    return created_at is not None and created_at <= stop_before


async def collect_all_bizinfo_notices(session: AsyncSession) -> CollectionResult:
    """기업마당 공고를 첫 페이지부터 끝까지 전부 수집한다.

    빈 페이지가 나오면 끝으로 간주한다 (page=9999처럼 끝을 넘어가도
    에러 없이 빈 리스트를 주는 것을 실제 호출로 확인함). 페이지마다
    커밋해서 트랜잭션이 지나치게 커지는 것을 막는다.

    조기종료: 직전 수집 시각(source.updated_at) 이전에 등록된 공고를
    만나면 그 이후는 이미 다 확인한 것으로 보고 멈춘다 (첫 수집이면
    updated_at이 없어 조기종료 없이 전부 훑는다). 반드시
    get_or_create_source *이전에* 직전 시각을 읽어야 한다 —
    get_or_create_source 자체가 updated_at을 지금 시각으로 갱신한다.
    """
    since = await get_source_updated_at(session, BIZINFO_SOURCE_NAME)
    stop_before = since - _BIZINFO_EARLY_STOP_BUFFER if since is not None else None

    source = await get_or_create_source(
        session,
        source_name=BIZINFO_SOURCE_NAME,
        base_url="https://www.bizinfo.go.kr",
        collect_type="API",
    )
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


async def _save_kstartup_attachments(
    session: AsyncSession, notice_id: int, pbanc_sn: str
) -> None:
    """K-Startup 상세페이지를 크롤링해 첨부파일 메타데이터만 저장한다.

    현재 수집 파이프라인(_process_kstartup_item)에서는 호출하지 않는다.
    기업마당과 달리 K-Startup은 목록 API 응답에 첨부파일 정보가 없어
    이 함수 자체가 상세페이지를 여는 크롤링이라(app/crawler/
    kstartup_attachment_client.py 참고), 전체 공고에 대해 매번 돌리면
    "매칭 후보로 좁혀진 것만 무거운 작업 한다"는 원칙에 어긋난다.
    수집 시점이 아니라 매칭 후보로 좁혀진 공고에 대해서만, 2차 필터링
    단계(docs/matching-pipeline.md 4단계)에서 호출하는 용도로 남겨둔다.
    텍스트 추출(OCR)도 이 함수가 아니라 그 단계에서 별도로 수행한다.

    공고 저장 자체와는 독립적인 부가 작업이라, 실패해도 공고 저장 결과에는
    영향을 주지 않도록 별도 SAVEPOINT로 격리한다. 상세페이지 조회(외부 HTTP,
    재시도 포함 최대 KSTARTUP_REQUEST_TIMEOUT_SECONDS × KSTARTUP_MAX_RETRIES까지
    걸릴 수 있음)는 SAVEPOINT 밖에서 먼저 끝내고, DB에 쓰는 부분만 짧게
    SAVEPOINT로 감싼다 — 안에서 같이 하면 느린 외부 요청 동안 DB 커넥션과
    트랜잭션을 계속 붙잡고 있게 된다.
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
                category_id=category_mapping.get(_kstartup_raw_category_key(item)),
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
    category_mapping = await get_category_mapping(session)
    items = await fetch_kstartup_notices(page=page)

    collection_result = CollectionResult()
    for item in items:
        await _process_kstartup_item(
            session, source.id, item, collection_result, category_mapping
        )

    await session.commit()
    return collection_result


# K-Startup 목록 API에는 등록시각 필드가 없다(신청시작일 pbanc_rcpt_bgng_dt는
# 등록순과 안 맞는 것을 실측 확인함 — 예: pbanc_sn 178487이 7/8, 바로 다음
# 178486이 7/9). 순서가 보장되는 값은 pbanc_sn(정수 일련번호)뿐이라 이걸
# 커서로 쓰되, 새 컬럼 없이 "이미 저장된 공고 중 가장 큰 external_id"로
# 대신한다 — 자금 카테고리만 저장하므로 이 값은 "마지막으로 확인한 지점"
# 보다 항상 같거나 작다(놓치는 방향이 아니라 더 훑는 방향으로만 어긋남).
# 여기에 추가로 여유분을 둔다 — pbanc_sn이 먼저 채번되고 공개는 나중에
# 되는 경우(관공서 시스템에서 흔함) 이미 지나친 것처럼 보이는 번호가
# 나중에 나타날 수 있어서다.
_KSTARTUP_EARLY_STOP_BUFFER = 200


def _kstartup_item_before_cutoff(item: dict, stop_below: int | None) -> bool:
    """이 항목이 조기종료 기준 pbanc_sn보다 작은(=이미 확인한 범위) 항목인지 판단한다."""
    if stop_below is None:
        return False
    pbanc_sn = item.get("pbanc_sn")
    return isinstance(pbanc_sn, int) and pbanc_sn <= stop_below


async def collect_all_kstartup_notices(session: AsyncSession) -> CollectionResult:
    """K-Startup 공고를 첫 페이지부터 끝까지 전부 수집한다.

    K-Startup은 전체가 29,000건 이상이라 페이지 수가 많다(perPage=100
    기준 약 290페이지). 빈 페이지가 나오면 끝으로 간주하고, 페이지마다
    커밋한다 (collect_all_bizinfo_notices와 동일한 이유).

    조기종료: _KSTARTUP_EARLY_STOP_BUFFER 설명 참고.
    """
    source = await get_or_create_source(
        session,
        source_name=KSTARTUP_SOURCE_NAME,
        base_url="https://www.k-startup.go.kr",
        collect_type="API",
    )
    max_saved_id = await get_max_notice_external_id(session, source.id)
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

    _process_bizinfo_item/_process_kstartup_item에 category_id 매핑을
    붙이기 전에 이미 저장돼 있던 공고들은 category_id가 NULL로 남는다.
    외부 API를 다시 호출하지 않고, 그때 같이 저장해 둔 원본 응답
    (bizinfo_raw/kstartup_raw.field)만으로 category_mapping과 대조해
    채운다.
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
            # raw_field는 항상 save_raw()에서 json.dumps()로 채워지지만,
            # 컬럼 자체는 NULL을 허용해서(레거시 데이터·수동 조작 가능성)
            # 여기서 깨지면 json.loads가 예외를 던진다. 한 건 때문에
            # 나머지 수천 건 백필이 통째로 실패하면 안 되므로(수집
            # 파이프라인의 SAVEPOINT 격리와 같은 이유), 이 건만 건너뛴다.
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
    """마감일이 지났는데 status가 아직 갱신 안 된 공고를 오늘 날짜 기준으로
    다시 계산한다 (수집 시점에만 계산해서 저장해두는 값이라, 재수집 없이는
    시간이 지나도 저절로 안 바뀜).

    외부 API를 다시 호출하지 않고, 이미 저장된 application_start_date/
    application_end_date만으로 재계산한다 — 날짜 자체는 수집 이후 바뀌지
    않으므로 이 값만으로 충분하다. 단, "확인필요"였던 공고를 "모집중"으로
    바꿔줬던 상시모집 판단(reqstBeginEndDe의 "상시"/"예산 소진" 등 키워드,
    _is_rolling_open)은 원본 문자열을 다시 안 부르면 재현할 수 없어서,
    재계산 결과가 "확인필요"인데 기존 상태가 "모집중"이면 건드리지 않는다
    (상시모집 공고가 여기서 잘못 마감 취급되는 걸 막기 위함).

    지금은 직접 호출하는 용도이고, 나중에 만들 스케줄러가 주기적으로
    호출해서 마감 처리를 최신 상태로 유지하는 데 쓴다.
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
            await update_notice_status(session, notice_id, new_status, new_is_actionable)
            updated += 1

    await session.commit()
    return {"checked": checked, "updated": updated}
