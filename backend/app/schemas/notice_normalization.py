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
