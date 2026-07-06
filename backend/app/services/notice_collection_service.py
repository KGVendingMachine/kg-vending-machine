import json
from datetime import date, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.crawler.bizinfo_client import fetch_bizinfo_notices
from app.crawler.kstartup_client import fetch_kstartup_notices
from app.models.raw import BizinfoRaw, KstartupRaw
from app.repositories.notice_repository import (
    get_or_create_organization,
    get_or_create_source,
    replace_notice_region,
    replace_notice_target_type,
    save_raw,
    upsert_notice,
)

BIZINFO_SOURCE_NAME = "기업마당"
KSTARTUP_SOURCE_NAME = "K-Startup"


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
        return None, None


def _parse_kstartup_date(value: str | None) -> date | None:
    """ "YYYYMMDD" 형식 문자열을 date로 변환한다."""
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except ValueError:
        return None


def _region_code_from_name(region_name: str) -> str:
    """지역명을 region_code로 변환한다.

    K-Startup 응답(supt_regin)은 지역명만 주고 실제 행정표준코드를
    주지 않는다. "전국"은 모델 주석대로 "ALL"로 매핑하고, 그 외
    지역은 정식 코드 테이블이 없어 지역명 자체를 임시 코드로 쓴다.
    정확한 행정표준코드 매핑은 별도 이슈로 남긴다.
    """
    if region_name == "전국":
        return "ALL"
    return region_name


def _derive_status_from_end_date(end_date: date | None) -> tuple[str, bool]:
    """기업마당 응답에는 모집 상태 플래그가 없어 마감일 기준으로 추정한다.

    실제 상태 플래그가 존재하는지는 COL-002(정규화) 단계에서 원본 raw
    데이터를 보며 다시 검토가 필요할 수 있다. 지금은 수집·적재만 다룬다.
    """
    if end_date is None:
        return "확인필요", False
    is_open = end_date >= date.today()
    return ("모집중" if is_open else "마감"), is_open


async def collect_bizinfo_notices(session: AsyncSession, page: int = 1) -> int:
    """기업마당 공고를 한 페이지 수집해 notice/bizinfo_raw에 저장하고 저장된 건수를 반환한다.

    API가 돌려준 개수(len(items))가 아니라, external_id가 없어 skip된
    항목을 뺀 실제 저장 건수를 반환한다.
    """
    source = await get_or_create_source(
        session,
        source_name=BIZINFO_SOURCE_NAME,
        base_url="https://www.bizinfo.go.kr",
        collect_type="API",
    )
    items = await fetch_bizinfo_notices(page=page)

    saved_count = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        external_id = item.get("pblancId")
        if not external_id:
            continue

        start_date, end_date = _parse_bizinfo_date_range(item.get("reqstBeginEndDe"))
        status, is_actionable = _derive_status_from_end_date(end_date)

        organization_id = None
        organization_name = item.get("jrsdInsttNm")
        if organization_name:
            organization = await get_or_create_organization(session, organization_name)
            organization_id = organization.id

        notice_id = await upsert_notice(
            session,
            source_id=source.id,
            external_id=external_id,
            title=item.get("pblancNm"),
            organization_id=organization_id,
            # 기업마당 응답에는 재공고/연장공고를 나타내는 필드가 확인되지
            # 않아 notice_group_key는 비워둔다 (K-Startup의 intg_pbanc_yn과
            # 달리 별도 이슈로 조사 필요).
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

        target_type = item.get("trgetNm")
        if target_type:
            await replace_notice_target_type(session, notice_id, target_type)
        # 기업마당 응답에서 지원지역을 나타내는 필드가 확인되지 않아
        # notice_region은 채우지 않는다 (별도 이슈로 조사 필요).

        saved_count += 1

    await session.commit()
    return saved_count


async def collect_kstartup_notices(session: AsyncSession, page: int = 1) -> int:
    """K-Startup 공고를 한 페이지 수집해 notice/kstartup_raw에 저장하고 저장된 건수를 반환한다.

    API가 돌려준 개수(len(items))가 아니라, pbanc_sn이 없어 skip된
    항목을 뺀 실제 저장 건수를 반환한다.
    """
    source = await get_or_create_source(
        session,
        source_name=KSTARTUP_SOURCE_NAME,
        base_url="https://www.k-startup.go.kr",
        collect_type="API",
    )
    items = await fetch_kstartup_notices(page=page)

    saved_count = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        pbanc_sn = item.get("pbanc_sn")
        if not pbanc_sn:
            continue
        external_id = str(pbanc_sn)

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
            organization = await get_or_create_organization(session, organization_name)
            organization_id = organization.id

        # intg_pbanc_yn(통합공고여부)이 "Y"면 intg_pbanc_biz_nm(통합공고
        # 사업명)이 재공고/연장공고를 묶는 상위 이름 역할을 한다. 이 값을
        # notice_group_key로 써서 같은 통합공고 아래 공고들을 묶는다.
        notice_group_key = None
        if item.get("intg_pbanc_yn") == "Y":
            notice_group_key = item.get("intg_pbanc_biz_nm")

        notice_id = await upsert_notice(
            session,
            source_id=source.id,
            external_id=external_id,
            title=item.get("biz_pbanc_nm"),
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

        target_type = item.get("aply_trgt")
        if target_type:
            await replace_notice_target_type(session, notice_id, target_type)

        region_name = item.get("supt_regin")
        if region_name:
            region_code = _region_code_from_name(region_name)
            await replace_notice_region(session, notice_id, region_code, region_name)

        saved_count += 1

    await session.commit()
    return saved_count
