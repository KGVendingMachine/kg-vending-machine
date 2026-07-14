from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, model_validator


class BookmarkCreateRequest(BaseModel):
    """북마크 생성 요청.

    추천 카드에서 담을 땐 match_result_id 만 넘기면 서버가 공고·사업계획서·
    점수 맥락을 여기서 채운다(source=recommendation). 공고 목록 브라우징에서
    담을 땐 notice_id 만 넘긴다(source=browse). 둘 중 정확히 하나만 보낸다.
    """

    notice_id: int | None = None
    match_result_id: int | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> "BookmarkCreateRequest":
        if (self.notice_id is None) == (self.match_result_id is None):
            raise ValueError("notice_id 와 match_result_id 중 정확히 하나만 보내세요.")
        return self


class BookmarkNoticeInfo(BaseModel):
    """북마크 카드에 표시할 공고 요약."""

    id: int
    title: str | None
    organization_name: str | None
    category_name: str | None
    status: str | None
    application_end_date: date | None
    amount_label: str | None
    source_url: str | None
    apply_url: str | None


class BookmarkRecommendation(BaseModel):
    """담을 당시(frozen) 추천 근거. match_result 에서 읽어온다."""

    total_score: Decimal | None
    recommendation_level: str | None
    summary_reason: str | None


class BookmarkResponse(BaseModel):
    """생성/조회 공통 북마크 표현."""

    id: int
    source: str
    business_plan_id: int | None
    business_plan_title: str | None
    is_stale: bool
    """이 추천의 기반 사업계획서가 현재 최신 계획서와 다른지. 브라우징 북마크는 항상 False."""
    notice: BookmarkNoticeInfo
    recommendation: BookmarkRecommendation | None
    """추천으로 담은 경우에만. 브라우징 북마크는 None."""
    created_at: datetime
