import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.config import get_settings


class SampleBusinessPlanError(Exception):
    """Base error for sample business plan loading failures."""


class SampleDataConfigError(SampleBusinessPlanError):
    """Raised when no sample JSON path is configured or provided."""


class SampleDataLoadError(SampleBusinessPlanError):
    """Raised when the sample JSON file cannot be read or parsed."""


class SampleNotFoundError(SampleBusinessPlanError):
    """Raised when a requested sample index does not exist."""


class SampleRawTextMissingError(SampleBusinessPlanError):
    """Raised when a sample row has no usable raw_text."""


@dataclass(frozen=True)
class SampleBusinessPlan:
    sample_index: int
    file_name: str | None
    file_type: str | None
    char_count: int | None
    raw_text: str


def _resolve_sample_path(sample_path: str | None = None) -> Path:
    configured_path = sample_path or get_settings().BUSINESS_PLAN_SAMPLE_JSON_PATH
    if not configured_path:
        raise SampleDataConfigError(
            "Sample JSON path is required. Provide sample_path or set "
            "BUSINESS_PLAN_SAMPLE_JSON_PATH."
        )
    return Path(configured_path).expanduser()


def _load_json_array(path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SampleDataLoadError(f"Failed to read sample JSON: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SampleDataLoadError(f"Failed to parse sample JSON: {path}") from exc

    if not isinstance(payload, list):
        raise SampleDataLoadError("Sample JSON root must be an array.")

    rows: list[dict[str, Any]] = []
    for row in payload:
        if not isinstance(row, dict):
            raise SampleDataLoadError("Every sample JSON item must be an object.")
        rows.append(row)
    return rows


def load_sample_business_plan(
    sample_index: int, sample_path: str | None = None
) -> SampleBusinessPlan:
    path = _resolve_sample_path(sample_path)
    rows = _load_json_array(path)

    if sample_index < 0 or sample_index >= len(rows):
        raise SampleNotFoundError(f"Sample index {sample_index} was not found.")

    row = rows[sample_index]
    raw_text = row.get("raw_text")
    if not isinstance(raw_text, str) or not raw_text.strip():
        raise SampleRawTextMissingError(f"Sample index {sample_index} has no raw_text.")

    file_name = row.get("file_name")
    file_type = row.get("file_type")
    char_count = row.get("char_count")
    return SampleBusinessPlan(
        sample_index=sample_index,
        file_name=file_name if isinstance(file_name, str) else None,
        file_type=file_type if isinstance(file_type, str) else None,
        char_count=char_count if isinstance(char_count, int) else None,
        raw_text=raw_text,
    )
