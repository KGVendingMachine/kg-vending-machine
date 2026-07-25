from datetime import date
from typing import Any

from pydantic import BaseModel, Field, field_validator

SCHEMA_VERSION = "1.0"


def _none_to_empty_list(value: Any) -> Any:
    return [] if value is None else value


def _list_to_joined_string(value: Any) -> Any:
    if isinstance(value, list):
        return ", ".join(str(item) for item in value if item)
    return value


class NoticeBasicInfo(BaseModel):
    title: str | None = None
    organization: str | None = None
    business_year: int | None = None
    source: str | None = None
    category: str | None = None
    status: str | None = None
    source_url: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class NoticeApplicationInfo(BaseModel):
    start_date: date | None = None
    end_date: date | None = None
    method: str | None = None
    apply_url: str | None = None
    submission_channel: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)

    # LLM이 값이 없을 때 null 대신 빈 리스트를 돌려주는 경우가 실측으로 확인됨
    # (2026-07-14, 정규화 실패 61건 중 대다수가 이 필드 하나 때문이었음).
    # NoticeContactInfo의 scalar 필드들과 같은 이유로 리스트를 문자열로
    # 흡수한다 — 스키마를 엄격하게 만드는 대신 LLM 출력의 사소한 형식
    # 흔들림을 받는 쪽에서 관대하게 처리한다.
    _normalize_submission_channel = field_validator(
        "submission_channel",
        mode="before",
    )(_list_to_joined_string)


class NoticeSupportInfo(BaseModel):
    summary: str | None = None
    support_type: list[str] = Field(default_factory=list)
    support_content: list[str] = Field(default_factory=list)
    support_amount: str | None = None
    subsidy_rate: str | None = None
    self_payment_required: bool | None = None
    support_period: str | None = None
    selection_count: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)

    _normalize_lists = field_validator(
        "support_type",
        "support_content",
        mode="before",
    )(_none_to_empty_list)


class NoticeEligibilityInfo(BaseModel):
    target_business_stage: list[str] = Field(default_factory=list)
    target_company_size: list[str] = Field(default_factory=list)
    target_industries: list[str] = Field(default_factory=list)
    target_regions: list[str] = Field(default_factory=list)
    business_age_min: int | None = None
    business_age_max: int | None = None
    required_status: list[str] = Field(default_factory=list)
    excluded_targets: list[str] = Field(default_factory=list)
    applicant_structure: str | None = None
    """신청 주체 구조. "단독 신청 가능" / "컨소시엄 필요(기업 주관/참여 가능)" /
    "컨소시엄·기관 전용(기업 참여 불가)" 중 하나. R&D 공고 실측(300건) 기준
    80%가 컨소시엄/연구기관 신청구조라, 그중 기업이 아예 참여 불가능한
    공고를 매칭 후보에서 걸러내기 위한 필드."""
    extra: dict[str, Any] = Field(default_factory=dict)

    _normalize_lists = field_validator(
        "target_business_stage",
        "target_company_size",
        "target_industries",
        "target_regions",
        "required_status",
        "excluded_targets",
        mode="before",
    )(_none_to_empty_list)


class NoticeEvaluationInfo(BaseModel):
    criteria: list[str] = Field(default_factory=list)
    preferred_conditions: list[str] = Field(default_factory=list)
    disqualification_reasons: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)

    _normalize_lists = field_validator(
        "criteria",
        "preferred_conditions",
        "disqualification_reasons",
        mode="before",
    )(_none_to_empty_list)


class NoticeDocumentInfo(BaseModel):
    required_documents: list[str] = Field(default_factory=list)
    optional_documents: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)

    _normalize_lists = field_validator(
        "required_documents",
        "optional_documents",
        mode="before",
    )(_none_to_empty_list)


class NoticeContactInfo(BaseModel):
    department: str | None = None
    manager: str | None = None
    phone: str | None = None
    email: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)

    _normalize_scalar_contacts = field_validator(
        "department",
        "manager",
        "phone",
        "email",
        mode="before",
    )(_list_to_joined_string)


class NoticeMatchingInfo(BaseModel):
    keywords: list[str] = Field(default_factory=list)
    suitable_company_profile: str | None = None
    matching_signals: list[str] = Field(default_factory=list)
    caution_points: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)

    _normalize_lists = field_validator(
        "keywords",
        "matching_signals",
        "caution_points",
        mode="before",
    )(_none_to_empty_list)


class NormalizedNoticeSchema(BaseModel):
    schema_version: str = SCHEMA_VERSION
    basic: NoticeBasicInfo = Field(default_factory=NoticeBasicInfo)
    application: NoticeApplicationInfo = Field(default_factory=NoticeApplicationInfo)
    support: NoticeSupportInfo = Field(default_factory=NoticeSupportInfo)
    eligibility: NoticeEligibilityInfo = Field(default_factory=NoticeEligibilityInfo)
    evaluation: NoticeEvaluationInfo = Field(default_factory=NoticeEvaluationInfo)
    documents: NoticeDocumentInfo = Field(default_factory=NoticeDocumentInfo)
    contact: NoticeContactInfo = Field(default_factory=NoticeContactInfo)
    matching: NoticeMatchingInfo = Field(default_factory=NoticeMatchingInfo)
    extra: dict[str, Any] = Field(default_factory=dict)
