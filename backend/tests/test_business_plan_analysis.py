"""
tests/test_business_plan_analysis.py

services.business_plan_analysis_service.run_analysis 테스트.
OCR(extract_fn)·정규화(normalize_fn)는 외부 호출이라 가짜 함수로 주입한다.
"""

import pytest

from app.models.business_plan import BusinessPlan
from app.models.company import CompanyProfile
from app.repositories.business_plan_repository import (
    BusinessPlanNotFoundError,
    get_by_id,
)
from app.ai.normalizer import AiNormalizationError
from app.schemas.business_plan import (
    NormalizedBusinessPlanSchema,
    ProblemInfo,
)
from app.schemas.business_plan_analysis import AnalysisStep
from app.services.business_plan_analysis_service import (
    NoUploadedFileError,
    run_analysis,
)
from app.services.business_plan_service import NoSourceTextError

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def stub_business_plan_embedding(monkeypatch):
    """Keep analysis tests independent from the optional embedding backend.

    Embedding failures are deliberately swallowed by ``run_analysis``, but the
    resulting session rollback expires ORM instances.  Whether that happened
    previously depended on the CI environment and could make a later
    synchronous ``plan.id`` access raise ``MissingGreenlet``.
    """

    async def _ensure_embedded(session, business_plan_id):
        return None

    monkeypatch.setattr(
        "app.services.business_plan_analysis_service.ensure_business_plan_embedded",
        _ensure_embedded,
    )


async def _create_plan(
    db_session, profile: CompanyProfile, **overrides
) -> BusinessPlan:
    defaults = dict(
        company_profile_id=profile.id,
        title="테스트 사업계획서",
        file_url="storage/uploads/test.pdf",
        file_type="PDF",
    )
    defaults.update(overrides)
    plan = BusinessPlan(**defaults)
    db_session.add(plan)
    await db_session.flush()
    return plan


def _fake_extract(text: str, file_type: str = "PDF"):
    async def _extract(path: str) -> tuple[str, str]:
        return text, file_type

    return _extract


def _fake_normalize(result: NormalizedBusinessPlanSchema):
    async def _normalize(text: str) -> NormalizedBusinessPlanSchema:
        return result

    return _normalize


async def test_run_analysis_saves_raw_text_and_analysis_json(
    db_session, test_company_profile
):
    plan = await _create_plan(db_session, test_company_profile)
    normalized = NormalizedBusinessPlanSchema(problem=ProblemInfo(background="배경"))

    outcome = await run_analysis(
        db_session,
        plan.id,
        extract_fn=_fake_extract("OCR로 뽑은 원문"),
        normalize_fn=_fake_normalize(normalized),
    )

    assert outcome.normalized == normalized

    fetched = await get_by_id(db_session, plan.id)
    assert fetched.raw_text == "OCR로 뽑은 원문"
    assert fetched.analysis_json == normalized.model_dump()
    assert fetched.analyzed_at is not None


async def test_run_analysis_preserves_ocr_result_when_normalize_fails(
    db_session, test_company_profile
):
    """정규화가 실패해도, 먼저 커밋한 OCR 결과(raw_text)는 남아야 한다."""
    plan = await _create_plan(db_session, test_company_profile)

    async def failing_normalize(text: str) -> NormalizedBusinessPlanSchema:
        raise AiNormalizationError("LLM 실패")

    with pytest.raises(AiNormalizationError):
        await run_analysis(
            db_session,
            plan.id,
            extract_fn=_fake_extract("보존돼야 할 원문"),
            normalize_fn=failing_normalize,
        )

    # save_raw_text는 Core UPDATE라 ORM 캐시를 갱신하지 않으므로, 커밋된 DB 값을
    # 다시 읽어 확인한다(운영에선 폴링이 새 세션으로 조회하므로 자연히 최신값).
    await db_session.refresh(plan)
    assert plan.raw_text == "보존돼야 할 원문"  # OCR 결과는 커밋되어 남음
    assert plan.analysis_json is None  # 정규화는 실패했으므로 비어 있음


async def test_run_analysis_skips_ocr_when_raw_text_exists(
    db_session, test_company_profile
):
    """raw_text가 이미 있으면(정규화만 실패했던 재시도) 재OCR 없이 정규화만 돈다."""
    plan = await _create_plan(
        db_session, test_company_profile, raw_text="이전 실행에서 추출해 둔 원문"
    )
    normalized = NormalizedBusinessPlanSchema(problem=ProblemInfo(background="배경"))
    steps: list[AnalysisStep] = []

    async def never_extract(path: str) -> tuple[str, str]:
        raise AssertionError("raw_text가 있으면 extract_fn을 부르면 안 된다")

    captured_text: list[str] = []

    async def capture_normalize(text: str) -> NormalizedBusinessPlanSchema:
        captured_text.append(text)
        return normalized

    async def record_step(step: AnalysisStep) -> None:
        steps.append(step)

    outcome = await run_analysis(
        db_session,
        plan.id,
        extract_fn=never_extract,
        normalize_fn=capture_normalize,
        on_step=record_step,
    )

    assert outcome.normalized == normalized
    assert captured_text == ["이전 실행에서 추출해 둔 원문"]
    assert steps == [AnalysisStep.NORMALIZING]  # extracting 단계는 건너뜀


async def test_run_analysis_skips_ocr_when_raw_text_is_empty_string(
    db_session, test_company_profile
):
    """raw_text는 None(아직 추출 안 함)과 ""(추출은 했지만 텍스트가 없었음,
    예: 빈 스캔본)을 구분해야 한다 — truthy 체크를 쓰면 빈 문자열도 "아직"
    으로 오인해 재-OCR(비싼 CLOVA 호출)을 다시 돌리게 된다.

    빈 문자열은 정규화할 원문이 없다는 뜻이라 결국 NoSourceTextError로
    끝나는 건 맞다(정상 동작) — 다만 거기까지 가는 과정에서 이미 있는
    raw_text를 무시하고 extract_fn을 또 부르면 안 된다."""
    plan = await _create_plan(db_session, test_company_profile, raw_text="")

    async def never_extract(path: str) -> tuple[str, str]:
        raise AssertionError(
            "raw_text가 이미 있으면(빈 문자열이어도) extract_fn을 부르면 안 된다"
        )

    async def never_normalize(text: str) -> NormalizedBusinessPlanSchema:
        raise AssertionError("정규화할 원문이 없으면 normalize_fn을 부르면 안 된다")

    with pytest.raises(NoSourceTextError):
        await run_analysis(
            db_session,
            plan.id,
            extract_fn=never_extract,
            normalize_fn=never_normalize,
        )


async def test_run_analysis_raises_when_plan_missing(db_session):
    with pytest.raises(BusinessPlanNotFoundError):
        await run_analysis(
            db_session,
            999_999,
            extract_fn=_fake_extract("x"),
            normalize_fn=_fake_normalize(NormalizedBusinessPlanSchema()),
        )


async def test_run_analysis_raises_when_no_uploaded_file(
    db_session, test_company_profile
):
    plan = await _create_plan(db_session, test_company_profile, file_url=None)

    with pytest.raises(NoUploadedFileError):
        await run_analysis(
            db_session,
            plan.id,
            extract_fn=_fake_extract("x"),
            normalize_fn=_fake_normalize(NormalizedBusinessPlanSchema()),
        )
