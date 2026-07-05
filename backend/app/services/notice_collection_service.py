import json
from datetime import date, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.crawler.bizinfo_client import fetch_bizinfo_notices
from app.crawler.kstartup_client import fetch_kstartup_notices
from app.models.raw import BizinfoRaw, KstartupRaw
from app.repositories.notice_repository import get_or_create_source, save_raw, upsert_notice

BIZINFO_SOURCE_NAME = "기업마당"
KSTARTUP_SOURCE_NAME = "K-Startup"


def _parse_bizinfo_date_range(value: str | None) -> tuple[date | None, date | None]:
    """"2026-07-27 ~ 2026-07-30" 형식 문자열을 (시작일, 종료일)로 변환한다."""
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
    """"YYYYMMDD" 형식 문자열을 date로 변환한다."""
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except ValueError:
        return None


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

        notice_id = await upsert_notice(
            session,
            source_id=source.id,
            external_id=external_id,
            title=item.get("pblancNm"),
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
        if pbanc_sn is None:
            continue
        external_id = str(pbanc_sn)

        start_date = _parse_kstartup_date(item.get("pbanc_rcpt_bgng_dt"))
        end_date = _parse_kstartup_date(item.get("pbanc_rcpt_end_dt"))
        is_actionable = item.get("rcrt_prgs_yn") == "Y"
        status = "모집중" if is_actionable else "마감"
        apply_url = item.get("biz_aply_url") or item.get("aply_mthd_onli_rcpt_istc")

        notice_id = await upsert_notice(
            session,
            source_id=source.id,
            external_id=external_id,
            title=item.get("biz_pbanc_nm"),
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
        saved_count += 1

    await session.commit()
    return saved_count
