"""
services/notice_normalization_helpers.py

공고 정규화(AI팀 normalize_notice_text 호출 결과)에 프롬프트 원문 메타데이터를
보완하는 로직. app/api/notice_samples.py(샘플 JSON 기준)와 app/api/
notice_normalization.py(실제 DB 공고 기준) 둘 다 같은 보완 규칙을 쓰므로
여기서 공유한다 — 원래 notice_samples.py에만 있던 로직을 그대로 옮긴 것이라
규칙 자체는 바뀌지 않았다.
"""

import re
from datetime import date

from app.schemas.notice_normalization import NormalizedNoticeSchema


def build_notice_prompt_text(
    *, label: str, metadata: dict[str, str], raw_text: str
) -> str:
    metadata_lines = [f"{key}: {value}" for key, value in metadata.items()]
    return (
        f"{label} 메타데이터:\n"
        + "\n".join(metadata_lines)
        + "\n\n첨부파일/상세공고문 OCR 원문:\n"
        + raw_text
    )


def _append_unique(values: list[str], label: str) -> None:
    if label not in values:
        values.append(label)


def _has_keyword(values: list[str], keyword: str) -> bool:
    return any(keyword in value for value in values)


def _enrich_support_types(raw_text: str, normalized: NormalizedNoticeSchema) -> None:
    support_text = "\n".join([raw_text, *normalized.support.support_content])
    rules = (
        (
            (
                "등록",
                "출원",
                "특허",
                "실용신안",
                "의장",
                "상표",
                "지적재산권",
                "산업재산권",
            ),
            "지식재산권",
        ),
        (("세미나", "교육", "워크숍", "워크샵"), "교육"),
        (
            (
                "인증",
                "ISO",
                "이노비즈",
                "메인비즈",
                "벤처",
                "NET",
                "NEP",
                "KS",
                "CE",
                "RoHS",
                "FDA",
                "HACCP",
            ),
            "인증지원",
        ),
        (("홍보", "카탈로그", "동영상", "홈페이지", "제작"), "홍보지원"),
        (
            (
                "시험",
                "성능시험",
                "신뢰성",
                "환경시험",
                "전자파",
                "소재시험",
                "제품성적서",
            ),
            "시험/인증",
        ),
        (("전문기술", "기술적 문제", "전문가", "컨설팅", "매칭"), "기술지원"),
        (("전투실험", "군 ", "국방", "방산", "방위산업"), "국방/방산"),
        (("비용", "지원금", "지원예산", "부담금", "만원", "억원", "%"), "자금지원"),
        (("수출", "해외", "무역", "글로벌"), "수출지원"),
        (("판로", "마케팅", "판매", "입점", "플래그십", "스토어"), "판로/마케팅"),
        (("공간", "시설", "회의실", "스튜디오", "대관"), "시설/공간"),
    )
    for keywords, label in rules:
        if any(keyword in support_text for keyword in keywords):
            _append_unique(normalized.support.support_type, label)


def _enrich_support_rates(raw_text: str, normalized: NormalizedNoticeSchema) -> None:
    source_text = "\n".join([raw_text, *normalized.support.support_content])
    has_support_90 = bool(re.search(r"90\s*%", source_text))
    has_self_payment_10 = bool(
        re.search(r"(기업부담금|자부담|부담금).{0,20}10\s*%", source_text)
    )

    if has_support_90:
        normalized.support.subsidy_rate = "90%"

    if has_self_payment_10:
        normalized.support.self_payment_required = True
        if not _has_keyword(normalized.matching.caution_points, "기업부담금"):
            _append_unique(
                normalized.matching.caution_points,
                "기업부담금은 공급가액의 10% 이상입니다.",
            )


def enrich_normalized_notice(
    normalized: NormalizedNoticeSchema,
    *,
    title: str | None,
    source: str | None,
    category: str | None,
    status: str | None,
    application_start_date: date | None,
    application_end_date: date | None,
    raw_text: str,
) -> NormalizedNoticeSchema:
    """LLM이 놓치기 쉬운 값을 원문 메타데이터/키워드로 보완한다.

    LLM 결과를 신뢰하되(이미 채워진 값은 덮어쓰지 않음), 비어 있는 값만
    메타데이터나 원문 키워드 매칭으로 채운다.
    """
    normalized.basic.title = normalized.basic.title or title
    normalized.basic.source = normalized.basic.source or source
    normalized.basic.category = normalized.basic.category or category
    normalized.basic.status = normalized.basic.status or status
    normalized.application.start_date = (
        normalized.application.start_date or application_start_date
    )
    normalized.application.end_date = (
        normalized.application.end_date or application_end_date
    )

    if not normalized.application.method:
        if re.search(r"[\w.+-]+@[\w.-]+", raw_text):
            normalized.application.method = "이메일 제출"
        elif "온라인" in raw_text or "홈페이지" in raw_text:
            normalized.application.method = "온라인 신청"

    if not normalized.application.submission_channel:
        if re.search(r"[\w.+-]+@[\w.-]+", raw_text):
            normalized.application.submission_channel = "이메일"
        elif "온라인" in raw_text or "홈페이지" in raw_text:
            normalized.application.submission_channel = "온라인"

    company_size_keywords = (
        ("소상공인", "소상공인"),
        ("중소", "중소기업"),
        ("중견", "중견기업"),
        ("벤처", "벤처기업"),
    )
    existing_company_sizes = set(normalized.eligibility.target_company_size)
    for keyword, label in company_size_keywords:
        if keyword in raw_text and label not in existing_company_sizes:
            normalized.eligibility.target_company_size.append(label)
            existing_company_sizes.add(label)

    _enrich_support_types(raw_text, normalized)
    _enrich_support_rates(raw_text, normalized)

    return normalized
