import json

import pytest

from app.services.sample_notice_loader import (
    SampleNoticeConfigError,
    SampleNoticeLoadError,
    SampleNoticeNotFoundError,
    SampleNoticeRawTextMissingError,
    load_sample_notice,
)


def _write_samples(tmp_path, payload) -> str:
    path = tmp_path / "notice_ocr_samples.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


def test_load_sample_notice_returns_selected_raw_text(tmp_path):
    sample_path = _write_samples(
        tmp_path,
        [
            {
                "title": "first notice",
                "raw_text": "one",
            },
            {
                "pbanc_nm": "second notice",
                "source_name": "bizinfo",
                "category": "export",
                "status": "open",
                "application_start_date": "2026-01-01",
                "application_end_date": "2026-12-31",
                "file_name": "notice.pdf",
                "file_type": "PDF",
                "char_count": 6,
                "raw_text": "source",
            },
        ],
    )

    sample = load_sample_notice(sample_index=1, sample_path=sample_path)

    assert sample.sample_index == 1
    assert sample.title == "second notice"
    assert sample.source == "bizinfo"
    assert sample.category == "export"
    assert sample.status == "open"
    assert sample.application_start_date == "2026-01-01"
    assert sample.application_end_date == "2026-12-31"
    assert sample.file_name == "notice.pdf"
    assert sample.file_type == "PDF"
    assert sample.char_count == 6
    assert sample.raw_text == "source"


def test_load_sample_notice_requires_path(monkeypatch):
    monkeypatch.setattr(
        "app.services.sample_notice_loader.get_settings",
        lambda: type("Settings", (), {"NOTICE_SAMPLE_JSON_PATH": ""})(),
    )

    with pytest.raises(SampleNoticeConfigError):
        load_sample_notice(sample_index=0)


def test_load_sample_notice_rejects_non_array_json(tmp_path):
    sample_path = _write_samples(tmp_path, {"raw_text": "source"})

    with pytest.raises(SampleNoticeLoadError):
        load_sample_notice(sample_index=0, sample_path=sample_path)


def test_load_sample_notice_rejects_missing_index(tmp_path):
    sample_path = _write_samples(tmp_path, [{"raw_text": "source"}])

    with pytest.raises(SampleNoticeNotFoundError):
        load_sample_notice(sample_index=1, sample_path=sample_path)


def test_load_sample_notice_requires_raw_text(tmp_path):
    sample_path = _write_samples(tmp_path, [{"title": "empty notice"}])

    with pytest.raises(SampleNoticeRawTextMissingError):
        load_sample_notice(sample_index=0, sample_path=sample_path)


def test_load_sample_notice_falls_back_to_raw_text_length(tmp_path):
    sample_path = _write_samples(tmp_path, [{"raw_text": "source"}])

    sample = load_sample_notice(sample_index=0, sample_path=sample_path)

    assert sample.char_count == 6
