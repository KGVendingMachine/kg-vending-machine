import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.config import get_settings


class SampleNoticeError(Exception):
    """Base error for sample notice loading failures."""


class SampleNoticeConfigError(SampleNoticeError):
    """Raised when no sample JSON path is configured or provided."""


class SampleNoticeLoadError(SampleNoticeError):
    """Raised when the sample JSON file cannot be read or parsed."""


class SampleNoticeNotFoundError(SampleNoticeError):
    """Raised when a requested sample index does not exist."""


class SampleNoticeRawTextMissingError(SampleNoticeError):
    """Raised when a sample row has no usable raw_text."""


@dataclass(frozen=True)
class SampleNotice:
    sample_index: int
    title: str | None
    source: str | None
    category: str | None
    status: str | None
    application_start_date: str | None
    application_end_date: str | None
    file_name: str | None
    file_type: str | None
    char_count: int
    raw_text: str


def _first_string(row: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _resolve_sample_path(sample_path: str | None = None) -> Path:
    configured_path = sample_path or get_settings().NOTICE_SAMPLE_JSON_PATH
    if not configured_path:
        raise SampleNoticeConfigError(
            "Sample JSON path is required. Provide sample_path or set "
            "NOTICE_SAMPLE_JSON_PATH."
        )
    return Path(configured_path).expanduser()


def _load_json_array(path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SampleNoticeLoadError(f"Failed to read sample JSON: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SampleNoticeLoadError(f"Failed to parse sample JSON: {path}") from exc

    if not isinstance(payload, list):
        raise SampleNoticeLoadError("Sample JSON root must be an array.")

    rows: list[dict[str, Any]] = []
    for row in payload:
        if not isinstance(row, dict):
            raise SampleNoticeLoadError("Every sample JSON item must be an object.")
        rows.append(row)
    return rows


def load_sample_notice(sample_index: int, sample_path: str | None = None) -> SampleNotice:
    path = _resolve_sample_path(sample_path)
    rows = _load_json_array(path)

    if sample_index < 0 or sample_index >= len(rows):
        raise SampleNoticeNotFoundError(f"Sample index {sample_index} was not found.")

    row = rows[sample_index]
    raw_text = row.get("raw_text")
    if not isinstance(raw_text, str) or not raw_text.strip():
        raise SampleNoticeRawTextMissingError(
            f"Sample index {sample_index} has no raw_text."
        )

    char_count = row.get("char_count")
    return SampleNotice(
        sample_index=sample_index,
        title=_first_string(row, ("title", "notice_title", "pbanc_nm", "biz_pbanc_nm")),
        source=_first_string(row, ("source", "source_name", "site", "provider")),
        category=_first_string(row, ("category", "category_name")),
        status=_first_string(row, ("status", "notice_status")),
        application_start_date=_first_string(row, ("application_start_date",)),
        application_end_date=_first_string(row, ("application_end_date",)),
        file_name=_first_string(row, ("file_name", "attachment_name", "atch_file_nm")),
        file_type=_first_string(row, ("file_type", "extension", "file_ext")),
        char_count=char_count if isinstance(char_count, int) else len(raw_text),
        raw_text=raw_text,
    )
