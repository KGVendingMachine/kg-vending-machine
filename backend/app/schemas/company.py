"""기업 프로필 요청/응답 스키마.

매칭 파이프라인(1·2차 필터링)이 기업 쪽 비교 축으로 쓰는 컬럼까지 다룬다:
사업자유형(business_type) · 기업 단계(company_stage) · 업종(industry_code) ·
지역(region_name→region_code) · 설립연도(founded_year→founded_date) · 매출.

단위/형식 변환 규칙:
- 설립연도: 요청은 연도(int)로 받고 서비스에서 founded_date(1월 1일)로 변환.
- 지역: 요청은 시/도 이름으로 받고 서비스에서 행정표준코드(region_code)를 함께 채움.
- 매출(annual_revenue): 요청/응답/DB 모두 원 단위. 억원 입력창의 환산은 프론트 담당.

요청은 부분 갱신을 지원한다: 보낸 필드만 반영하고 나머지 컬럼은 그대로 둔다.
"""

from datetime import date

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# 사업자유형 (models/company.py business_type 컬럼과 동일한 값 집합)
BUSINESS_TYPES = ("개인사업자", "법인사업자", "예비창업자")

# 기업 단계 (company_stage 컬럼). 소상공인은 단계가 아니라 규모라 여기 두지
# 않는다 — 규모는 company_size로 별도 산출한다(services/company_size.py).
COMPANY_STAGES = ("예비창업자", "초기창업", "중소기업")

# 예비창업자만 가질 수 있는 기업 단계. business_type과의 정합성 검증에 사용.
PRE_FOUNDER_TYPE = "예비창업자"
PRE_FOUNDER_STAGE = "예비창업자"

# 시/도 이름 → 행정표준코드(법정동코드 시도 2자리).
# 강원(51)·전북(52)은 특별자치도 승격 이후 코드를 사용한다(구 42·45 아님).
REGION_CODES: dict[str, str] = {
    "서울": "11",
    "부산": "26",
    "대구": "27",
    "인천": "28",
    "광주": "29",
    "대전": "30",
    "울산": "31",
    "세종": "36",
    "경기": "41",
    "충북": "43",
    "충남": "44",
    "전남": "46",
    "경북": "47",
    "경남": "48",
    "제주": "50",
    "강원": "51",
    "전북": "52",
}

# 한국표준산업분류(KSIC) 대분류 코드 → 명칭.
# 지원사업 신청 주체가 될 수 없는 O(공공행정)·T(가구내 고용)·U(국제기관)는 제외.
KSIC_INDUSTRIES: dict[str, str] = {
    "A": "농업, 임업 및 어업",
    "B": "광업",
    "C": "제조업",
    "D": "전기, 가스, 증기 및 공기 조절 공급업",
    "E": "수도, 하수 및 폐기물 처리, 원료 재생업",
    "F": "건설업",
    "G": "도매 및 소매업",
    "H": "운수 및 창고업",
    "I": "숙박 및 음식점업",
    "J": "정보통신업",
    "K": "금융 및 보험업",
    "L": "부동산업",
    "M": "전문, 과학 및 기술 서비스업",
    "N": "사업시설 관리, 사업 지원 및 임대 서비스업",
    "P": "교육 서비스업",
    "Q": "보건업 및 사회복지 서비스업",
    "R": "예술, 스포츠 및 여가관련 서비스업",
    "S": "협회 및 단체, 수리 및 기타 개인 서비스업",
}

_STRING_FIELDS = (
    "representative_name",
    "business_registration_number",
    "business_type",
    "company_stage",
    "industry_code",
    "region_name",
)


class CompanyProfileUpdate(BaseModel):
    """기업 프로필 부분 갱신 요청. JSON에 담아 보낸 필드만 반영된다."""

    representative_name: str | None = Field(None, max_length=100)
    business_registration_number: str | None = Field(None, max_length=20)
    # company_size는 사용자 입력을 받지 않는다 — 업종·매출에서 서버가 산출한다
    # (services/company_size.derive_company_size). 응답 스키마에만 남긴다.
    employee_count: int | None = Field(None, ge=0)
    business_type: str | None = Field(
        None, description="개인사업자 / 법인사업자 / 예비창업자"
    )
    company_stage: str | None = Field(None, description="예비창업자 / 초기창업 / 중소기업")
    industry_code: str | None = Field(None, description="KSIC 대분류 코드 (A~S)")
    region_name: str | None = Field(None, description="사업장 시/도 이름")
    founded_year: int | None = Field(None, ge=1900, description="설립연도 (예: 2021)")
    annual_revenue: int | None = Field(None, ge=0, description="연매출 (원)")

    @field_validator(*_STRING_FIELDS, "employee_count", mode="before")
    @classmethod
    def _blank_to_none(cls, value: object) -> object:
        """빈 문자열("")은 미입력으로 보고 None 처리한다(폼 select 기본값 대응)."""
        if isinstance(value, str) and value.strip() == "":
            return None
        return value

    @field_validator("business_type")
    @classmethod
    def _validate_business_type(cls, value: str | None) -> str | None:
        if value is not None and value not in BUSINESS_TYPES:
            raise ValueError(f"business_type은 {BUSINESS_TYPES} 중 하나여야 합니다")
        return value

    @field_validator("company_stage")
    @classmethod
    def _validate_company_stage(cls, value: str | None) -> str | None:
        if value is not None and value not in COMPANY_STAGES:
            raise ValueError(f"company_stage는 {COMPANY_STAGES} 중 하나여야 합니다")
        return value

    @field_validator("industry_code")
    @classmethod
    def _validate_industry_code(cls, value: str | None) -> str | None:
        if value is not None and value not in KSIC_INDUSTRIES:
            raise ValueError("industry_code는 KSIC 대분류 코드(A~S)여야 합니다")
        return value

    @field_validator("region_name")
    @classmethod
    def _validate_region_name(cls, value: str | None) -> str | None:
        if value is not None and value not in REGION_CODES:
            raise ValueError(f"region_name은 {tuple(REGION_CODES)} 중 하나여야 합니다")
        return value

    @field_validator("founded_year")
    @classmethod
    def _validate_founded_year(cls, value: int | None) -> int | None:
        if value is not None and value > date.today().year:
            raise ValueError("founded_year는 미래 연도일 수 없습니다")
        return value

    @model_validator(mode="after")
    def _validate_stage_matches_business_type(self) -> "CompanyProfileUpdate":
        """한 요청 안에 business_type과 company_stage가 함께 오면 조합을 검증한다.

        하나만 온 부분 갱신은 여기서 판단할 수 없다(기존 저장값과 합쳐봐야
        판단 가능) — 그 경우는 company_service에서 기존 프로필과 병합해 검증한다.
        """
        if self.business_type is None or self.company_stage is None:
            return self
        is_pre_founder = self.business_type == PRE_FOUNDER_TYPE
        is_pre_founder_stage = self.company_stage == PRE_FOUNDER_STAGE
        if is_pre_founder != is_pre_founder_stage:
            raise ValueError(
                "사업자유형과 기업 단계 조합이 올바르지 않습니다"
                "(예비창업자는 기업 단계가 예비창업자여야 하고, 그 외에는 예비창업자일 수 없습니다)"
            )
        return self


class CompanyProfileResponse(BaseModel):
    """저장된 기업 프로필(본인). 아직 다루지 않는 컬럼은 응답에서 생략한다."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    representative_name: str | None = None
    business_registration_number: str | None = None
    company_size: str | None = None
    employee_count: int | None = None
    business_type: str | None = None
    company_stage: str | None = None
    industry_code: str | None = None
    region_code: str | None = None
    region_name: str | None = None
    founded_date: date | None = None
    annual_revenue: int | None = None
    """연매출 (원)"""
