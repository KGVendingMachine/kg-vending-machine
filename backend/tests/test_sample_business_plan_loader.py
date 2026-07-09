import json

import pytest

from app.services.sample_business_plan_loader import (
    SampleDataConfigError,
    SampleDataLoadError,
    SampleNotFoundError,
    SampleRawTextMissingError,
    load_sample_business_plan,
)


def _write_samples(tmp_path, payload) -> str:
    path = tmp_path / "ocr_samples.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


def test_load_sample_business_plan_returns_selected_raw_text(tmp_path):
    sample_path = _write_samples(
        tmp_path,
        [
            {
                "file_name": "first.pdf",
                "file_type": "PDF",
                "char_count": 3,
                "raw_text": "one",
            },
            {
                "file_name": "second.hwpx",
                "file_type": "HWPX",
                "char_count": 6,
                "raw_text": "source",
            },
        ],
    )

    sample = load_sample_business_plan(sample_index=1, sample_path=sample_path)

    assert sample.sample_index == 1
    assert sample.file_name == "second.hwpx"
    assert sample.file_type == "HWPX"
    assert sample.char_count == 6
    assert sample.raw_text == "source"


def test_load_sample_business_plan_requires_path(monkeypatch):
    monkeypatch.setattr(
        "app.services.sample_business_plan_loader.get_settings",
        lambda: type("Settings", (), {"BUSINESS_PLAN_SAMPLE_JSON_PATH": ""})(),
    )

    with pytest.raises(SampleDataConfigError):
        load_sample_business_plan(sample_index=0)


def test_load_sample_business_plan_rejects_non_array_json(tmp_path):
    sample_path = _write_samples(tmp_path, {"raw_text": "source"})

    with pytest.raises(SampleDataLoadError):
        load_sample_business_plan(sample_index=0, sample_path=sample_path)


def test_load_sample_business_plan_rejects_missing_index(tmp_path):
    sample_path = _write_samples(tmp_path, [{"raw_text": "source"}])

    with pytest.raises(SampleNotFoundError):
        load_sample_business_plan(sample_index=1, sample_path=sample_path)


def test_load_sample_business_plan_requires_raw_text(tmp_path):
    sample_path = _write_samples(tmp_path, [{"file_name": "empty.pdf"}])

    with pytest.raises(SampleRawTextMissingError):
        load_sample_business_plan(sample_index=0, sample_path=sample_path)
