import json

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.ai.normalizer import AiNormalizationError
from app.api.notice_samples import (
    SampleNoticeNormalizationRequest,
    _enrich_from_sample_metadata,
    normalize_sample_notice,
)
from app.main import app
from app.schemas.notice import (
    NormalizedNoticeSchema,
    NoticeApplicationInfo,
    NoticeBasicInfo,
    NoticeEligibilityInfo,
    NoticeMatchingInfo,
    NoticeSupportInfo,
)
from app.services.notice_service import validate_normalized_notice
from app.services.sample_notice_loader import SampleNotice

pytestmark = pytest.mark.anyio


def _complete_normalized() -> NormalizedNoticeSchema:
    return NormalizedNoticeSchema(
        basic=NoticeBasicInfo(title="수입규제 대응 컨설팅"),
        application=NoticeApplicationInfo(method="이메일 제출"),
        support=NoticeSupportInfo(
            summary="수입규제 대응 컨설팅 지원",
            support_type=["컨설팅"],
            support_content=["컨설팅 비용 지원"],
        ),
        eligibility=NoticeEligibilityInfo(target_company_size=["중소기업"]),
        matching=NoticeMatchingInfo(
            keywords=["수입규제", "컨설팅"],
            suitable_company_profile="수입규제 대응이 필요한 중소기업",
            matching_signals=["중소기업", "수입규제", "컨설팅 필요"],
        ),
    )


def _write_samples(tmp_path) -> str:
    path = tmp_path / "notice_ocr_samples.json"
    path.write_text(
        json.dumps(
            [
                {
                    "title": "수입규제 대응 컨설팅",
                    "source": "sample",
                    "category": "수출",
                    "status": "모집중",
                    "application_start_date": "2026-03-01",
                    "application_end_date": "2026-12-31",
                    "file_name": "notice.pdf",
                    "file_type": "PDF",
                    "char_count": 11,
                    "raw_text": "sample text",
                }
            ]
        ),
        encoding="utf-8",
    )
    return str(path)


async def test_normalize_sample_notice_returns_normalized_result(
    tmp_path, monkeypatch
):
    sample_path = _write_samples(tmp_path)
    seen_texts: list[str] = []

    async def fake_normalize(text: str) -> NormalizedNoticeSchema:
        seen_texts.append(text)
        return _complete_normalized()

    monkeypatch.setattr("app.api.notice_samples.normalize_notice_text", fake_normalize)

    response = await normalize_sample_notice(
        SampleNoticeNormalizationRequest(sample_index=0, sample_path=sample_path)
    )

    assert "sample text" in seen_texts[0]
    assert "title: 수입규제 대응 컨설팅" in seen_texts[0]
    assert "application_start_date: 2026-03-01" in seen_texts[0]
    assert response.sample_index == 0
    assert response.title == "수입규제 대응 컨설팅"
    assert response.source == "sample"
    assert response.category == "수출"
    assert response.status == "모집중"
    assert response.application_start_date == "2026-03-01"
    assert response.application_end_date == "2026-12-31"
    assert response.file_name == "notice.pdf"
    assert response.file_type == "PDF"
    assert response.char_count == 11
    assert response.normalized_json.basic.title == "수입규제 대응 컨설팅"
    assert response.normalized_json.basic.source == "sample"
    assert response.normalized_json.basic.category == "수출"
    assert response.normalized_json.basic.status == "모집중"
    assert str(response.normalized_json.application.start_date) == "2026-03-01"
    assert str(response.normalized_json.application.end_date) == "2026-12-31"
    assert response.validation_result.is_valid is True


async def test_normalize_sample_notice_raises_400_for_loader_errors():
    with pytest.raises(HTTPException) as exc_info:
        await normalize_sample_notice(
            SampleNoticeNormalizationRequest(sample_index=0, sample_path="missing.json")
        )

    assert exc_info.value.status_code == 400


async def test_normalize_sample_notice_raises_502_for_ai_errors(
    tmp_path, monkeypatch
):
    sample_path = _write_samples(tmp_path)

    async def fake_normalize(text: str) -> NormalizedNoticeSchema:
        raise AiNormalizationError("failed")

    monkeypatch.setattr("app.api.notice_samples.normalize_notice_text", fake_normalize)

    with pytest.raises(HTTPException) as exc_info:
        await normalize_sample_notice(
            SampleNoticeNormalizationRequest(sample_index=0, sample_path=sample_path)
        )

    assert exc_info.value.status_code == 502


def test_sample_notice_route_is_available(tmp_path, monkeypatch):
    sample_path = _write_samples(tmp_path)

    async def fake_normalize(text: str) -> NormalizedNoticeSchema:
        return _complete_normalized()

    monkeypatch.setattr("app.api.notice_samples.normalize_notice_text", fake_normalize)

    client = TestClient(app)
    response = client.post(
        "/api/notices/samples/normalizations",
        json={"sample_index": 0, "sample_path": sample_path},
    )

    assert response.status_code == 200
    assert response.json()["title"] == "수입규제 대응 컨설팅"


def test_normalized_notice_schema_treats_null_arrays_as_empty_lists():
    normalized = NormalizedNoticeSchema.model_validate(
        {
            "support": {"support_content": None},
            "eligibility": {"target_industries": None},
            "evaluation": {"criteria": None},
            "documents": {"required_documents": None},
            "matching": {"keywords": None},
        }
    )

    assert normalized.support.support_content == []
    assert normalized.eligibility.target_industries == []
    assert normalized.evaluation.criteria == []
    assert normalized.documents.required_documents == []
    assert normalized.matching.keywords == []


def test_enrich_from_sample_metadata_adds_granular_support_types():
    sample = SampleNotice(
        sample_index=0,
        title="방산 헬프데스크",
        source="기업마당",
        category="기타",
        status="모집중",
        application_start_date="2025-01-02",
        application_end_date="2027-12-31",
        file_name="notice.pdf",
        file_type="PDF",
        char_count=100,
        raw_text=(
            "지적재산권 등록 출원, 세미나 교육 워크숍, 기업 인증, "
            "홍보물 제작, 환경시험, 전문기술 지원, 군 전투실험, 방산"
        ),
    )
    normalized = NormalizedNoticeSchema(
        support=NoticeSupportInfo(
            support_content=[
                "지적재산권 등록/출원비용 지원",
                "기업 인증 심사비 지원",
                "홍보물 제작 지원",
                "시험경비 지원",
                "전문기술 지원",
                "군 전투실험 지원",
            ]
        )
    )

    enriched = _enrich_from_sample_metadata(sample, normalized)

    assert "지식재산권" in enriched.support.support_type
    assert "교육" in enriched.support.support_type
    assert "인증지원" in enriched.support.support_type
    assert "홍보지원" in enriched.support.support_type
    assert "시험/인증" in enriched.support.support_type
    assert "기술지원" in enriched.support.support_type
    assert "국방/방산" in enriched.support.support_type


def test_enrich_from_sample_metadata_keeps_subsidy_and_self_payment_separate():
    sample = SampleNotice(
        sample_index=0,
        title="방산 헬프데스크",
        source="기업마당",
        category="기타",
        status="모집중",
        application_start_date="2025-01-02",
        application_end_date="2027-12-31",
        file_name="notice.pdf",
        file_type="PDF",
        char_count=100,
        raw_text=(
            "등록/출원비용의 90% 지원. 기업부담금은 공급가액의 10% 이상"
        ),
    )
    normalized = NormalizedNoticeSchema(
        support=NoticeSupportInfo(
            subsidy_rate="10%",
            self_payment_required=None,
            support_content=["등록/출원비용의 90% 지원"],
        ),
        matching=NoticeMatchingInfo(
            caution_points=["기업부담금은 공급가액의 10% 이상"]
        ),
    )

    enriched = _enrich_from_sample_metadata(sample, normalized)

    assert enriched.support.subsidy_rate == "90%"
    assert enriched.support.self_payment_required is True
    assert len(enriched.matching.caution_points) == 1


def test_validate_normalized_notice_reports_source_consistency_errors():
    normalized = _complete_normalized()
    normalized.support.subsidy_rate = "10%"
    normalized.support.self_payment_required = False
    source_text = (
        "등록/출원비용의 90% 지원. 기업부담금은 공급가액의 10% 이상. "
        "신청방법 이메일 제출(test@example.com). 문의 02-1234-5678. 제출서류"
    )

    result = validate_normalized_notice(normalized, source_text=source_text)

    assert result.is_valid is False
    assert any("subsidy_rate" in error for error in result.errors)
    assert any("self_payment_required" in error for error in result.errors)
    assert any("contact.email" in error for error in result.errors)
    assert any("contact.phone" in error for error in result.errors)
    assert any("required_documents" in error for error in result.errors)
