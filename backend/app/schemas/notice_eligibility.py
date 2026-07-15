from pydantic import BaseModel, Field


class EligibleNoticesResponse(BaseModel):
    """1차 필터(하드필터)를 통과한 공고 id 목록과 축별 집계."""

    notice_ids: list[int] = Field(description="하드필터를 통과한 notice.id 목록")
    counts: dict[str, int] = Field(
        description=(
            "축별 집계. 키: input(후보 수), 지역_탈락/대상_탈락/업력_탈락/"
            "기간_탈락, 통과. 순차 필터라 각 탈락은 그 축에서 처음 걸린 수."
        )
    )
