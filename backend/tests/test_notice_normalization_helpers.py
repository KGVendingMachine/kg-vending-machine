from app.schemas.notice_normalization import NormalizedNoticeSchema
from app.services.notice_normalization_helpers import enrich_normalized_notice


def _enrich(raw_text: str, normalized: NormalizedNoticeSchema | None = None):
    return enrich_normalized_notice(
        normalized or NormalizedNoticeSchema(),
        title=None,
        source=None,
        category=None,
        status=None,
        application_start_date=None,
        application_end_date=None,
        raw_text=raw_text,
    )


def test_applicant_structure_defaults_to_solo_without_consortium_hint():
    result = _enrich("중소기업을 대상으로 사업화 자금을 지원합니다.")
    assert result.eligibility.applicant_structure == "단독 신청 가능"


def test_applicant_structure_explicit_solo_wins_even_with_consortium_word():
    result = _enrich("단독 신청 가능하며, 컨소시엄 구성 시 가점을 부여합니다.")
    assert result.eligibility.applicant_structure == "단독 신청 가능"


def test_applicant_structure_consortium_with_company_hint_stays_open():
    result = _enrich("중소기업이 주관기관으로 참여하는 컨소시엄을 구성해 신청합니다.")
    assert (
        result.eligibility.applicant_structure == "컨소시엄 필요(기업 주관/참여 가능)"
    )


def test_applicant_structure_consortium_without_company_hint_is_institute_only():
    result = _enrich(
        "대학, 출연연 등 연구기관이 주관기관으로 컨소시엄을 구성해 신청합니다."
    )
    assert (
        result.eligibility.applicant_structure == "컨소시엄·기관 전용(기업 참여 불가)"
    )


def test_applicant_structure_does_not_overwrite_llm_value():
    normalized = NormalizedNoticeSchema()
    normalized.eligibility.applicant_structure = "단독 신청 가능"
    result = _enrich(
        "대학, 출연연 등 연구기관이 주관기관으로 컨소시엄을 구성해 신청합니다.",
        normalized,
    )
    assert result.eligibility.applicant_structure == "단독 신청 가능"
