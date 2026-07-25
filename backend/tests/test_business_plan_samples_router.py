import json

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.business_plan_samples import (
    SampleNormalizationRequest,
    normalize_sample_business_plan,
)
from app.ai.normalizer import AiNormalizationError
from app.main import app
from app.schemas.business_plan import (
    FundingInfo,
    NormalizedBusinessPlanSchema,
    ProblemInfo,
    SolutionInfo,
    TeamInfo,
)

pytestmark = pytest.mark.anyio


def _complete_normalized() -> NormalizedBusinessPlanSchema:
    return NormalizedBusinessPlanSchema(
        problem=ProblemInfo(background="background"),
        solution=SolutionInfo(summary="summary"),
        funding=FundingInfo(scale_up_strategy="strategy"),
        team=TeamInfo(capabilities="capabilities"),
    )


def _write_samples(tmp_path) -> str:
    path = tmp_path / "ocr_samples.json"
    path.write_text(
        json.dumps(
            [
                {
                    "file_name": "plan.pdf",
                    "file_type": "PDF",
                    "char_count": 11,
                    "raw_text": "sample text",
                }
            ]
        ),
        encoding="utf-8",
    )
    return str(path)


async def test_normalize_sample_business_plan_returns_normalized_result(
    tmp_path, monkeypatch
):
    sample_path = _write_samples(tmp_path)
    seen_texts: list[str] = []

    async def fake_normalize(text: str) -> NormalizedBusinessPlanSchema:
        seen_texts.append(text)
        return _complete_normalized()

    monkeypatch.setattr("app.api.business_plan_samples.normalize_text", fake_normalize)

    response = await normalize_sample_business_plan(
        SampleNormalizationRequest(sample_index=0, sample_path=sample_path)
    )

    assert seen_texts == ["sample text"]
    assert response.sample_index == 0
    assert response.file_name == "plan.pdf"
    assert response.file_type == "PDF"
    assert response.char_count == 11
    assert response.normalized_json == _complete_normalized()
    assert response.validation_result.is_valid is True


async def test_normalize_sample_business_plan_raises_400_for_loader_errors():
    with pytest.raises(HTTPException) as exc_info:
        await normalize_sample_business_plan(
            SampleNormalizationRequest(sample_index=0, sample_path="missing.json")
        )

    assert exc_info.value.status_code == 400


async def test_normalize_sample_business_plan_raises_502_for_ai_errors(
    tmp_path, monkeypatch
):
    sample_path = _write_samples(tmp_path)

    async def fake_normalize(text: str) -> NormalizedBusinessPlanSchema:
        raise AiNormalizationError("failed")

    monkeypatch.setattr("app.api.business_plan_samples.normalize_text", fake_normalize)

    with pytest.raises(HTTPException) as exc_info:
        await normalize_sample_business_plan(
            SampleNormalizationRequest(sample_index=0, sample_path=sample_path)
        )

    assert exc_info.value.status_code == 502


def test_sample_route_does_not_get_shadowed_by_business_plan_id_route(
    tmp_path, monkeypatch
):
    sample_path = _write_samples(tmp_path)

    async def fake_normalize(text: str) -> NormalizedBusinessPlanSchema:
        return _complete_normalized()

    monkeypatch.setattr("app.api.business_plan_samples.normalize_text", fake_normalize)

    client = TestClient(app)
    response = client.post(
        "/api/business-plans/samples/normalizations",
        json={"sample_index": 0, "sample_path": sample_path},
    )

    assert response.status_code == 200
    assert response.json()["file_name"] == "plan.pdf"
