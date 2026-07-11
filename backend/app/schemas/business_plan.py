"""
schemas/business_plan.py

NRM-001: 사업계획서 표준 정규화 API 스키마
POST /business-plans/{business_plan_id}/normalizations   -> 정규화 작업 시작 (202 Accepted)
GET  /business-plans/{business_plan_id}/normalizations/{job_id} -> 작업 상태/결과 조회


- 처리 방식: LLM 호출은 시간이 걸리므로 동기 응답 대신 비동기(202 + 상태 조회) 패턴 적용.
- 카테고리 체계: PSST(문제인식/실현가능성/성장전략/팀구성) 프레임워크 기반
  company / problem / solution / market / funding / team 6개 축으로 통일.
  회사별 특이 항목은 각 카테고리의 extra에 자유롭게 저장 (스키마리스 확장).

"""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "1.0"


# ---------------------------------------------------------------------------
# 카테고리별 서브 스키마
# ---------------------------------------------------------------------------


class CompanyInfo(BaseModel):
    """기업 개요"""

    name: str | None = None
    ceo_name: str | None = None
    founded_year: int | None = None
    industry: str | None = None
    business_registration_status: str | None = None
    """예비창업자 / 사업자등록 여부 등"""
    extra: dict[str, Any] = Field(default_factory=dict)


class ProblemInfo(BaseModel):
    """P - 문제 인식"""

    background: str | None = None
    """개발 동기, 시장 배경"""
    target_customer_pain_point: str | None = None
    """고객이 겪는 구체적 문제/불편"""
    market_problem: str | None = None
    """국내외 시장의 구조적 문제점"""
    extra: dict[str, Any] = Field(default_factory=dict)


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


class MarketInfo(BaseModel):
    """시장 분석"""

    target_market: str | None = None
    market_size: str | None = None
    target_customer_persona: str | None = None
    competitors: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)


class FundingInfo(BaseModel):
    """S2 - 성장전략 및 자금 수요"""

    amount_requested: float | None = None
    use_of_funds: list[str] = Field(default_factory=list)
    """사업화 자금 사용 계획"""
    scale_up_strategy: str | None = None
    """마케팅/판매채널/사업화 추진 전략"""
    extra: dict[str, Any] = Field(default_factory=dict)


class TeamInfo(BaseModel):
    """T - 팀 구성"""

    members: list[str] = Field(default_factory=list)
    capabilities: str | None = None
    """대표자 및 팀원 보유 경험, 기술력, 노하우"""
    extra: dict[str, Any] = Field(default_factory=dict)


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


class NormalizeRequest(BaseModel):
    """
    운영 환경 기본 흐름: body 없이 호출 -> 서버가 business_plan.raw_text를
    DB에서 조회해서 정규화 대상으로 사용.

    extracted_text는 [테스트 전용] 필드. 아직 실제 사업계획서 데이터를
    받지 못해 DB에 raw_text가 없는 현재 상황에서, 임시 텍스트로 정규화
    로직을 검증해보기 위해 남겨둠. 실 데이터 확보 후에는 이 필드를
    아예 제거하거나 관리자/디버그 전용 플래그로만 열어두는 것을 권장.
    """

    extracted_text: str | None = Field(
        default=None,
        description="[TEST ONLY] 실 데이터 확보 전, 임시 텍스트로 정규화를 테스트할 때만 사용",
    )


class NormalizeJobAccepted(BaseModel):
    """POST /business-plans/{business_plan_id}/normalizations 응답 (202 Accepted)"""

    business_plan_id: int
    job_id: str
    status: JobStatus = JobStatus.PENDING


class NormalizeStatusResponse(BaseModel):
    """GET /business-plans/{business_plan_id}/normalizations/{job_id} 응답"""

    business_plan_id: int
    job_id: str
    status: JobStatus
    normalized_json: NormalizedBusinessPlanSchema | None = None
    validation_result: ValidationResult | None = None
    analyzed_at: datetime | None = None
    error_message: str | None = None
    """status == failed 일 때 실패 사유 (예: LLM 재시도 초과, 스키마 검증 실패)"""
