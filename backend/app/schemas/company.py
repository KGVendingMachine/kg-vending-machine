"""기업 프로필 요청/응답 스키마.

지금은 폼과 DB 형식이 딱 맞는 컬럼만 다룬다. 단위/날짜/코드 변환이 필요한
매출(억원↔원)·설립일(연도↔Date)·업종/지역(라벨↔코드)은 추후 라운드에서
요청 스키마에 필드를 더하고 서비스에서 변환해 붙인다.

요청은 부분 갱신을 지원한다: 보낸 필드만 반영하고 나머지 컬럼은 그대로 둔다.
"""

from pydantic import BaseModel, ConfigDict, Field, field_validator

_STRING_FIELDS = (
    "representative_name",
    "business_registration_number",
    "company_size",
)


class CompanyProfileUpdate(BaseModel):
    """기업 프로필 부분 갱신 요청. JSON에 담아 보낸 필드만 반영된다."""

    representative_name: str | None = Field(None, max_length=100)
    business_registration_number: str | None = Field(None, max_length=20)
    company_size: str | None = Field(None, max_length=20)
    employee_count: int | None = Field(None, ge=0)

    @field_validator(*_STRING_FIELDS, "employee_count", mode="before")
    @classmethod
    def _blank_to_none(cls, value: object) -> object:
        """빈 문자열("")은 미입력으로 보고 None 처리한다(폼 select 기본값 대응)."""
        if isinstance(value, str) and value.strip() == "":
            return None
        return value


class CompanyProfileResponse(BaseModel):
    """저장된 기업 프로필(본인). 아직 다루지 않는 컬럼은 응답에서 생략한다."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    representative_name: str | None = None
    business_registration_number: str | None = None
    company_size: str | None = None
    employee_count: int | None = None
