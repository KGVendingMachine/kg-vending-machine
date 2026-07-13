"""
tests/test_notice_normalization_service.py

services/notice_normalization_service.py 테스트. conftest.db_session(SAVEPOINT
롤백) 위에서 실제 DB로 검증하고, 실제 OpenAI 호출(normalize_notice_text)과
실제 다운로드(download_and_extract_attachment)만 monkeypatch로 대체한다.

PDF/HWP/HWPX 첨부파일 후보 전부(+summary_text)를 각각 정규화해보고 검증
결과가 가장 좋은 것을 채택하는 방식(2026-07-13, 옵션4)이라, 대부분의
테스트가 "후보 여러 개 중 뭐가 채택되는지"를 확인하는 형태다.
"""

import pytest

from app.ai.normalizer import AiNormalizationError
from app.models.notice import Notice
from app.models.notice_source import NoticeSource
from app.repositories.notice_repository import (
    delete_notice,
    get_notice_attachments,
    save_attachment,
    set_attachment_parsed_text,
    upsert_notice,
)
from app.schemas.notice_normalization import (
    NoticeApplicationInfo,
    NoticeBasicInfo,
    NoticeEligibilityInfo,
    NoticeMatchingInfo,
    NoticeSupportInfo,
    NormalizedNoticeSchema,
)
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


def _empty_normalized() -> NormalizedNoticeSchema:
    return NormalizedNoticeSchema()


def _complete_normalized(title: str = "완전한 결과") -> NormalizedNoticeSchema:
    """REQUIRED_FIELDS(app/services/notice_service.py)를 전부 채운, 검증을
    통과하는 결과 — "품질 좋은 후보"를 흉내낼 때 쓴다."""
    return NormalizedNoticeSchema(
        basic=NoticeBasicInfo(title=title),
        application=NoticeApplicationInfo(method="이메일 제출"),
        support=NoticeSupportInfo(
            summary="지원 요약",
            support_type=["자금지원"],
            support_content=["지원 내용"],
        ),
        eligibility=NoticeEligibilityInfo(target_company_size=["중소기업"]),
        matching=NoticeMatchingInfo(
            keywords=["키워드"],
            suitable_company_profile="적합 프로필",
            matching_signals=["신호"],
        ),
    )


async def test_normalize_notice_picks_better_candidate_among_multiple(
    db_session, monkeypatch
):
    """첨부파일 후보가 2개면 둘 다 정규화해보고, 검증 결과(필수 필드 충족)가
    더 좋은 쪽이 채택돼야 한다."""
    source = await _create_source(db_session, "정규화테스트출처1")
    notice_id = await _create_notice(
        db_session, source, external_id="norm-1", summary_text="요약문"
    )
    await save_attachment(
        db_session, notice_id, "부실한원문.pdf", "https://example.com/a.pdf", "PDF"
    )
    await save_attachment(
        db_session, notice_id, "좋은원문.pdf", "https://example.com/b.pdf", "PDF"
    )
    attachments = await get_notice_attachments(db_session, notice_id)
    for attachment in attachments:
        if attachment.file_name == "부실한원문.pdf":
            await set_attachment_parsed_text(
                db_session, attachment.id, "부실한 OCR 원문"
            )
        else:
            await set_attachment_parsed_text(db_session, attachment.id, "좋은 OCR 원문")

    async def fake_normalize(prompt_text: str) -> NormalizedNoticeSchema:
        if "좋은 OCR 원문" in prompt_text:
            return _complete_normalized(title="좋은 후보 결과")
        return _empty_normalized()

    monkeypatch.setattr(svc, "normalize_notice_text", fake_normalize)

    outcome = await normalize_notice(db_session, notice_id)

    assert outcome.normalized.basic.title == "좋은 후보 결과"
    assert outcome.validation_result.is_valid is True

    notice = await db_session.get(Notice, notice_id)
    assert notice.normalization_status == "completed"
    assert notice.normalized_json["basic"]["title"] == "좋은 후보 결과"


async def test_normalize_notice_reuses_already_parsed_text_without_redownload(
    db_session, monkeypatch
):
    """이미 parsed_text가 있는 첨부파일은 다시 다운로드하지 않아야 한다
    (성공 캐싱 규칙)."""
    source = await _create_source(db_session, "정규화테스트출처2")
    notice_id = await _create_notice(db_session, source, external_id="norm-2")
    await save_attachment(
        db_session, notice_id, "이미처리됨.pdf", "https://example.com/a.pdf", "PDF"
    )
    attachment_id = (await get_notice_attachments(db_session, notice_id))[0].id
    await set_attachment_parsed_text(db_session, attachment_id, "이미 OCR된 원문")

    async def fail_if_called(source_name, attachment):
        raise AssertionError("이미 parsed_text가 있는데 다시 다운로드하면 안 됨")

    monkeypatch.setattr(svc, "download_and_extract_attachment", fail_if_called)

    async def fake_normalize(prompt_text: str) -> NormalizedNoticeSchema:
        assert "이미 OCR된 원문" in prompt_text
        return _complete_normalized()

    monkeypatch.setattr(svc, "normalize_notice_text", fake_normalize)

    outcome = await normalize_notice(db_session, notice_id)

    assert outcome.normalized.basic.title == "완전한 결과"


async def test_normalize_notice_skips_candidate_whose_download_fails(
    db_session, monkeypatch
):
    """후보 하나가 다운로드에 실패해도 나머지 후보로 정상 완료돼야 한다."""
    source = await _create_source(db_session, "정규화테스트출처3")
    notice_id = await _create_notice(db_session, source, external_id="norm-3")
    await save_attachment(
        db_session, notice_id, "실패할파일.pdf", "https://example.com/broken.pdf", "PDF"
    )
    await save_attachment(
        db_session, notice_id, "성공할파일.pdf", "https://example.com/ok.pdf", "PDF"
    )

    async def fake_download(source_name, attachment):
        if attachment.file_name == "실패할파일.pdf":
            raise RuntimeError("다운로드 실패")
        return "다운로드 성공한 원문"

    monkeypatch.setattr(svc, "download_and_extract_attachment", fake_download)

    async def fake_normalize(prompt_text: str) -> NormalizedNoticeSchema:
        return _complete_normalized()

    monkeypatch.setattr(svc, "normalize_notice_text", fake_normalize)

    outcome = await normalize_notice(db_session, notice_id)

    assert outcome.normalized.basic.title == "완전한 결과"

    attachments = await get_notice_attachments(db_session, notice_id)
    by_name = {a.file_name: a for a in attachments}
    assert by_name["실패할파일.pdf"].parsed_text is None  # 실패한 건 저장 안 됨
    assert by_name["성공할파일.pdf"].parsed_text == "다운로드 성공한 원문"


async def test_normalize_notice_falls_back_to_summary_text_when_no_attachments(
    db_session, monkeypatch
):
    source = await _create_source(db_session, "정규화테스트출처4")
    notice_id = await _create_notice(
        db_session, source, external_id="norm-4", summary_text="요약문만 있음"
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
    source = await _create_source(db_session, "정규화테스트출처5")
    notice_id = await _create_notice(
        db_session, source, external_id="norm-5", summary_text=None
    )

    with pytest.raises(NoSourceTextForNormalizationError):
        await normalize_notice(db_session, notice_id)

    notice = await db_session.get(Notice, notice_id)
    assert notice.normalization_status == "failed"
    assert "정규화에 쓸 원문이 없습니다" in notice.normalization_error
    assert notice.normalized_json is None


async def test_normalize_notice_persists_failure_status_when_all_candidates_fail(
    db_session, monkeypatch
):
    source = await _create_source(db_session, "정규화테스트출처6")
    notice_id = await _create_notice(
        db_session, source, external_id="norm-6", summary_text="요약문"
    )

    async def fake_normalize_failing(prompt_text: str) -> NormalizedNoticeSchema:
        raise AiNormalizationError("LLM 실패")

    monkeypatch.setattr(svc, "normalize_notice_text", fake_normalize_failing)

    with pytest.raises(AiNormalizationError):
        await normalize_notice(db_session, notice_id)

    notice = await db_session.get(Notice, notice_id)
    assert notice.normalization_status == "failed"
    assert "모두 시도했지만 전부 실패" in notice.normalization_error
    assert notice.normalized_json is None


async def test_normalize_notice_raises_not_found_when_notice_deleted_during_llm_call(
    db_session, monkeypatch
):
    """LLM 호출(길면 수십 초)이 도는 동안 다른 트랜잭션(크롤링의 "기업마당
    우선" 중복 정리 등)이 이 공고를 지울 수 있다 — 이 경우 저장이 0행
    반영되는데, 이를 확인하지 않으면 이미 사라진 공고에 COMPLETED를
    반환하게 된다(notice_ocr.py의 동일한 문제와 같은 원인). 실제로 재현
    확인함(2026-07-13)."""
    source = await _create_source(db_session, "정규화테스트출처7")
    notice_id = await _create_notice(
        db_session, source, external_id="norm-7", summary_text="요약문"
    )

    async def fake_normalize_with_concurrent_delete(
        prompt_text: str,
    ) -> NormalizedNoticeSchema:
        # LLM 응답을 기다리는 동안 다른 트랜잭션이 이 공고를 삭제하는
        # 상황을 재현 (실제로는 별도 커넥션이지만, 테스트에서는 같은
        # db_session으로 "그 사이 사라졌다"만 재현하면 충분하다).
        await delete_notice(db_session, notice_id)
        return _complete_normalized()

    monkeypatch.setattr(
        svc, "normalize_notice_text", fake_normalize_with_concurrent_delete
    )

    with pytest.raises(NoticeNotFoundForNormalizationError):
        await normalize_notice(db_session, notice_id)


async def test_normalize_notice_enriches_with_real_metadata(db_session, monkeypatch):
    """LLM 결과에 빠진 title/category는 실제 공고 메타데이터로 채워져야 한다
    (notice_samples.py의 _enrich_from_sample_metadata와 같은 규칙)."""
    source = await _create_source(db_session, "정규화테스트출처8")
    notice_id = await _create_notice(
        db_session,
        source,
        external_id="norm-8",
        title="실제 공고 제목",
        summary_text="중소기업 대상 지원 사업입니다.",
    )

    async def fake_normalize_empty(prompt_text: str) -> NormalizedNoticeSchema:
        return _empty_normalized()

    monkeypatch.setattr(svc, "normalize_notice_text", fake_normalize_empty)

    outcome = await normalize_notice(db_session, notice_id)

    assert outcome.normalized.basic.title == "실제 공고 제목"
    assert "중소기업" in outcome.normalized.eligibility.target_company_size
