"""
tests/test_notice_normalization_service.py

services/notice_normalization_service.py 테스트. conftest.db_session(SAVEPOINT
롤백) 위에서 실제 DB로 검증하고, 실제 OpenAI 호출(normalize_notice_text)만
monkeypatch로 대체한다.
"""

import pytest

from app.ai.normalizer import AiNormalizationError
from app.models.notice import Notice
from app.models.notice_source import NoticeSource
from app.repositories.notice_repository import (
    get_notice_attachments,
    save_attachment,
    set_attachment_parsed_text,
    upsert_notice,
)
from app.schemas.notice_normalization import NoticeBasicInfo, NormalizedNoticeSchema
from app.services import notice_normalization_service as svc
from app.services.notice_normalization_service import (
    NoSourceTextForNormalizationError,
    NoticeNotFoundForNormalizationError,
    normalize_notice,
)

pytestmark = pytest.mark.anyio


async def _create_source(db_session, name: str) -> NoticeSource:
    source = NoticeSource(source_name=name, base_url="https://example.com")
    db_session.add(source)
    await db_session.flush()
    return source


async def _create_notice(db_session, source: NoticeSource, **overrides) -> int:
    defaults = dict(
        source_id=source.id,
        external_id="norm-ext-1",
        title="테스트 공고",
        application_start_date=None,
        application_end_date=None,
        status="모집중",
        is_actionable=True,
        source_url=None,
        apply_url=None,
        summary_text=None,
    )
    defaults.update(overrides)
    return await upsert_notice(db_session, **defaults)


def _complete_normalized() -> NormalizedNoticeSchema:
    return NormalizedNoticeSchema(basic=NoticeBasicInfo(title="LLM이 뽑은 제목"))


async def test_normalize_notice_uses_ocr_text_when_available(db_session, monkeypatch):
    source = await _create_source(db_session, "정규화테스트출처1")
    notice_id = await _create_notice(
        db_session, source, external_id="norm-1", summary_text="요약문"
    )
    await save_attachment(
        db_session, notice_id, "공고문.pdf", "https://example.com/a.pdf", "PDF"
    )
    attachment_id = (await get_notice_attachments(db_session, notice_id))[0].id
    await set_attachment_parsed_text(db_session, attachment_id, "OCR로 뽑은 원문")

    seen_prompts: list[str] = []

    async def fake_normalize(prompt_text: str) -> NormalizedNoticeSchema:
        seen_prompts.append(prompt_text)
        return _complete_normalized()

    monkeypatch.setattr(svc, "normalize_notice_text", fake_normalize)

    outcome = await normalize_notice(db_session, notice_id)

    assert "OCR로 뽑은 원문" in seen_prompts[0]
    assert "요약문" not in seen_prompts[0]  # OCR 텍스트가 있으면 summary_text는 안 씀
    assert outcome.normalized.basic.title == "LLM이 뽑은 제목"

    notice = await db_session.get(Notice, notice_id)
    assert notice.normalization_status == "completed"
    assert notice.normalized_json is not None


async def test_normalize_notice_falls_back_to_summary_text_when_no_ocr(
    db_session, monkeypatch
):
    source = await _create_source(db_session, "정규화테스트출처2")
    notice_id = await _create_notice(
        db_session, source, external_id="norm-2", summary_text="요약문만 있음"
    )

    seen_prompts: list[str] = []

    async def fake_normalize(prompt_text: str) -> NormalizedNoticeSchema:
        seen_prompts.append(prompt_text)
        return _complete_normalized()

    monkeypatch.setattr(svc, "normalize_notice_text", fake_normalize)

    await normalize_notice(db_session, notice_id)

    assert "요약문만 있음" in seen_prompts[0]


async def test_normalize_notice_raises_not_found_for_unknown_id(db_session):
    with pytest.raises(NoticeNotFoundForNormalizationError):
        await normalize_notice(db_session, 999_999_999)


async def test_normalize_notice_raises_no_source_text_error(db_session):
    source = await _create_source(db_session, "정규화테스트출처3")
    notice_id = await _create_notice(
        db_session, source, external_id="norm-3", summary_text=None
    )

    with pytest.raises(NoSourceTextForNormalizationError):
        await normalize_notice(db_session, notice_id)


async def test_normalize_notice_persists_failure_status_on_ai_error(
    db_session, monkeypatch
):
    source = await _create_source(db_session, "정규화테스트출처4")
    notice_id = await _create_notice(
        db_session, source, external_id="norm-4", summary_text="요약문"
    )

    async def fake_normalize_failing(prompt_text: str) -> NormalizedNoticeSchema:
        raise AiNormalizationError("LLM 실패")

    monkeypatch.setattr(svc, "normalize_notice_text", fake_normalize_failing)

    with pytest.raises(AiNormalizationError):
        await normalize_notice(db_session, notice_id)

    notice = await db_session.get(Notice, notice_id)
    assert notice.normalization_status == "failed"
    assert notice.normalization_error == "LLM 실패"
    assert notice.normalized_json is None


async def test_normalize_notice_enriches_with_real_metadata(db_session, monkeypatch):
    """LLM 결과에 빠진 title/category는 실제 공고 메타데이터로 채워져야 한다
    (notice_samples.py의 _enrich_from_sample_metadata와 같은 규칙)."""
    source = await _create_source(db_session, "정규화테스트출처5")
    notice_id = await _create_notice(
        db_session,
        source,
        external_id="norm-5",
        title="실제 공고 제목",
        summary_text="중소기업 대상 지원 사업입니다.",
    )

    async def fake_normalize_empty(prompt_text: str) -> NormalizedNoticeSchema:
        return NormalizedNoticeSchema()  # title 등 전부 비어있는 결과

    monkeypatch.setattr(svc, "normalize_notice_text", fake_normalize_empty)

    outcome = await normalize_notice(db_session, notice_id)

    assert outcome.normalized.basic.title == "실제 공고 제목"
    assert "중소기업" in outcome.normalized.eligibility.target_company_size
