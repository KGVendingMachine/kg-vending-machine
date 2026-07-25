"""
schemas/business_plan.py

사업계획서 정규화 결과 스키마. 비동기 작업(OCR+정규화+임베딩) 자체는
api/business_plan_analysis.py + schemas/business_plan_analysis.py가 다룬다.

- 카테고리 체계: PSST(문제인식/실현가능성/성장전략/팀구성) 프레임워크 기반
  company / problem / solution / market / funding / team 6개 축으로 통일.
  회사별 특이 항목은 각 카테고리의 extra에 자유롭게 저장 (스키마리스 확장).

"""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

SCHEMA_VERSION = "1.1"


def _none_to_empty_dict(value: Any) -> Any:
    return {} if value is None else value


def _none_to_empty_list(value: Any) -> Any:
    return [] if value is None else value


# ---------------------------------------------------------------------------
# 카테고리별 서브 스키마
# ---------------------------------------------------------------------------


class IndustryCandidate(BaseModel):
    """Business/support field candidate used for matching."""

    label: str
    confidence: float | None = Field(default=None, ge=0, le=1)
    reason: str | None = None
    source_keywords: list[str] = Field(default_factory=list)

    _normalize_lists = field_validator("source_keywords", mode="before")(
        _none_to_empty_list
    )


class CompanyInfo(BaseModel):
    """기업 개요"""

    name: str | None = None
    ceo_name: str | None = None
    founded_year: int | None = None
    region_name: str | None = Field(
        default=None,
        description=(
            "사업장 소재지 시/도. 서울/부산/대구/인천/광주/대전/울산/세종/경기/"
            "충북/충남/전남/경북/경남/제주/강원/전북 중 하나"
        ),
    )
    business_type: str | None = Field(
        default=None,
        description="사업자 유형. 개인사업자/법인사업자/예비창업자 중 하나",
    )
    industry: str | None = None
    industry_candidates: list[IndustryCandidate] = Field(default_factory=list)
    business_registration_status: str | None = None
    """예비창업자 / 사업자등록 여부 등"""
    extra: dict[str, Any] = Field(default_factory=dict)
    _normalize_lists = field_validator("industry_candidates", mode="before")(
        _none_to_empty_list
    )
    _normalize_extra = field_validator("extra", mode="before")(_none_to_empty_dict)


class ProblemInfo(BaseModel):
    """P - 문제 인식"""

    background: str | None = None
    """개발 동기, 시장 배경"""
    target_customer_pain_point: str | None = None
    """고객이 겪는 구체적 문제/불편"""
    market_problem: str | None = None
    """국내외 시장의 구조적 문제점"""
    extra: dict[str, Any] = Field(default_factory=dict)
    _normalize_extra = field_validator("extra", mode="before")(_none_to_empty_dict)


class SolutionInfo(BaseModel):
    """S1 - 실현 가능성 (제품/서비스 포함)"""

    summary: str | None = None
    """비즈니스 모델(BM) 및 솔루션 개요"""
    product_description: str | None = None
    """제품/서비스 상세, 구현 정도"""
    development_stage: str | None = None
    """제작 소요기간 및 제작방법 (자체/외주 등)"""
    tech_stack: list[str] = Field(default_factory=list)
    differentiators: list[str] = Field(default_factory=list)
    """경쟁사 대비 우위 요소, 차별화 전략"""
    extra: dict[str, Any] = Field(default_factory=dict)
    _normalize_lists = field_validator(
        "tech_stack",
        "differentiators",
        mode="before",
    )(_none_to_empty_list)
    _normalize_extra = field_validator("extra", mode="before")(_none_to_empty_dict)


class MarketInfo(BaseModel):
    """시장 분석"""

    target_market: str | None = None
    market_size: str | None = None
    target_customer_persona: str | None = None
    competitors: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)
    _normalize_lists = field_validator("competitors", mode="before")(
        _none_to_empty_list
    )
    _normalize_extra = field_validator("extra", mode="before")(_none_to_empty_dict)


class FundingInfo(BaseModel):
    """S2 - 성장전략 및 자금 수요"""

    amount_requested: float | None = None
    use_of_funds: list[str] = Field(default_factory=list)
    """사업화 자금 사용 계획"""
    scale_up_strategy: str | None = None
    """마케팅/판매채널/사업화 추진 전략"""
    extra: dict[str, Any] = Field(default_factory=dict)
    _normalize_lists = field_validator("use_of_funds", mode="before")(
        _none_to_empty_list
    )
    _normalize_extra = field_validator("extra", mode="before")(_none_to_empty_dict)


class TeamInfo(BaseModel):
    """T - 팀 구성"""

    members: list[str] = Field(default_factory=list)
    capabilities: str | None = None
    """대표자 및 팀원 보유 경험, 기술력, 노하우"""
    extra: dict[str, Any] = Field(default_factory=dict)
    _normalize_lists = field_validator("members", mode="before")(_none_to_empty_list)
    _normalize_extra = field_validator("extra", mode="before")(_none_to_empty_dict)


# ---------------------------------------------------------------------------
# 정규화 결과 최상위 스키마
# ---------------------------------------------------------------------------


class NormalizedBusinessPlanSchema(BaseModel):
    schema_version: str = SCHEMA_VERSION
    company: CompanyInfo = Field(default_factory=CompanyInfo)
    problem: ProblemInfo = Field(default_factory=ProblemInfo)
    solution: SolutionInfo = Field(default_factory=SolutionInfo)
    market: MarketInfo = Field(default_factory=MarketInfo)
    funding: FundingInfo = Field(default_factory=FundingInfo)
    team: TeamInfo = Field(default_factory=TeamInfo)


class ValidationResult(BaseModel):
    is_valid: bool
    missing_required_fields: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    """LLM 재시도 이력, 파싱 오류 등"""


# ---------------------------------------------------------------------------
# 비동기 작업 상태
# ---------------------------------------------------------------------------


class JobStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# Request / Response 스키마
# ---------------------------------------------------------------------------


class BusinessPlanUploadResponse(BaseModel):
    """POST /business-plans 응답 (201 Created).

    업로드 후 다음 단계(분석 시작)에서 쓸 식별자를 돌려준다. 서버 내부 저장
    경로(file_url)는 노출하지 않는다.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str | None = None
    file_type: str | None = None


class BusinessPlanSummaryResponse(BaseModel):
    """GET /business-plans/me 응답. 파일 원본 경로(file_url)는 노출하지 않는다."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str | None = None
    file_type: str | None = None
    uploaded_at: datetime
    analysis_status: JobStatus | None = None
