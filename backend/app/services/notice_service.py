import re
from typing import Any

from app.schemas.business_plan import ValidationResult
from app.schemas.notice import NormalizedNoticeSchema

REQUIRED_FIELDS: tuple[str, ...] = (
    "basic.title",
    "application.method",
    "support.summary",
    "support.support_type",
    "support.support_content",
    "eligibility.target_company_size",
    "matching.keywords",
    "matching.suitable_company_profile",
    "matching.matching_signals",
)


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list | dict):
        return bool(value)
    return True


def _has_email(text: str) -> bool:
    return bool(re.search(r"[\w.+-]+@[\w.-]+", text))


def _has_phone(text: str) -> bool:
    return bool(re.search(r"\d{2,4}-\d{3,4}-\d{4}", text))


def _collect_source_consistency_errors(
    normalized: NormalizedNoticeSchema, source_text: str
) -> list[str]:
    errors: list[str] = []

    has_support_90 = bool(re.search(r"90\s*%", source_text))
    has_self_payment_10 = bool(
        re.search(r"(기업부담금|자부담|부담금).{0,20}10\s*%", source_text)
    )

    if has_support_90 and normalized.support.subsidy_rate != "90%":
        errors.append(
            "source.support.subsidy_rate: 원문에 90% 지원이 있으므로 subsidy_rate는 90%여야 합니다."
        )

    if has_self_payment_10 and normalized.support.subsidy_rate == "10%":
        errors.append(
            "source.support.subsidy_rate: 원문의 10%는 자부담률이므로 subsidy_rate에 넣으면 안 됩니다."
        )

    if has_self_payment_10 and normalized.support.self_payment_required is not True:
        errors.append(
            "source.support.self_payment_required: 원문에 기업부담금 10% 이상 조건이 있으므로 true여야 합니다."
        )

    if _has_email(source_text) and not _has_value(normalized.contact.email):
        errors.append("source.contact.email: 원문에 이메일이 있지만 contact.email이 비어 있습니다.")

    if _has_phone(source_text) and not _has_value(normalized.contact.phone):
        errors.append("source.contact.phone: 원문에 전화번호가 있지만 contact.phone이 비어 있습니다.")

    if "제출서류" in source_text and not _has_value(
        normalized.documents.required_documents
    ):
        errors.append(
            "source.documents.required_documents: 원문에 제출서류가 있지만 required_documents가 비어 있습니다."
        )

    if "신청방법" in source_text and not _has_value(normalized.application.method):
        errors.append(
            "source.application.method: 원문에 신청방법이 있지만 application.method가 비어 있습니다."
        )

    return errors


def validate_normalized_notice(
    normalized: NormalizedNoticeSchema, source_text: str | None = None
) -> ValidationResult:
    missing: list[str] = []
    errors: list[str] = []

    for field_path in REQUIRED_FIELDS:
        section_name, field_name = field_path.split(".", maxsplit=1)
        section = getattr(normalized, section_name)
        if not _has_value(getattr(section, field_name)):
            missing.append(field_path)

    if source_text:
        errors.extend(_collect_source_consistency_errors(normalized, source_text))

    return ValidationResult(
        is_valid=not missing and not errors,
        missing_required_fields=missing,
        errors=errors,
    )
