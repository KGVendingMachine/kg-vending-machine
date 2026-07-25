import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.config import get_settings

# API로 전달받은 sample_path는 이 디렉터리 하위 파일만 허용한다(경로 탈출 방지).
# 서버 설정값(NOTICE_SAMPLE_JSON_PATH)은 배포 환경에서 신뢰할 수 있는 값이므로 제한하지 않는다.
_SAMPLE_DATA_BASE_DIR = Path(__file__).resolve().parents[2] / "data"


class SampleNoticeError(Exception):
    """샘플 공고 로딩 실패에 대한 기본 예외."""


class SampleNoticeConfigError(SampleNoticeError):
    """샘플 JSON 경로가 설정되지 않았거나 허용되지 않은 경로일 때 발생."""


class SampleNoticeLoadError(SampleNoticeError):
    """샘플 JSON 파일을 읽거나 파싱할 수 없을 때 발생."""


class SampleNoticeNotFoundError(SampleNoticeError):
    """요청한 sample_index가 존재하지 않을 때 발생."""


class SampleNoticeRawTextMissingError(SampleNoticeError):
    """샘플 행에 사용 가능한 raw_text가 없을 때 발생."""


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


def _resolve_caller_sample_path(sample_path: str) -> Path:
    base_dir = _SAMPLE_DATA_BASE_DIR.resolve()
    candidate = (base_dir / sample_path).resolve()
    try:
        candidate.relative_to(base_dir)
    except ValueError as exc:
        raise SampleNoticeConfigError(
            "sample_path는 data 디렉터리 내부의 파일만 지정할 수 있습니다."
        ) from exc
    return candidate


def _resolve_sample_path(sample_path: str | None = None) -> Path:
    if sample_path:
        return _resolve_caller_sample_path(sample_path)

    configured_path = get_settings().NOTICE_SAMPLE_JSON_PATH
    if not configured_path:
        raise SampleNoticeConfigError(
            "샘플 JSON 경로가 필요합니다. sample_path를 전달하거나 "
            "NOTICE_SAMPLE_JSON_PATH를 설정하세요."
        )
    return Path(configured_path).expanduser()


def _load_json_array(path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SampleNoticeLoadError(f"샘플 JSON을 읽을 수 없습니다: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SampleNoticeLoadError(f"샘플 JSON을 파싱할 수 없습니다: {path}") from exc

    if not isinstance(payload, list):
        raise SampleNoticeLoadError("샘플 JSON의 최상위 구조는 배열이어야 합니다.")

    rows: list[dict[str, Any]] = []
    for row in payload:
        if not isinstance(row, dict):
            raise SampleNoticeLoadError("샘플 JSON의 각 항목은 객체여야 합니다.")
        rows.append(row)
    return rows


def load_sample_notice(
    sample_index: int, sample_path: str | None = None
) -> SampleNotice:
    path = _resolve_sample_path(sample_path)
    rows = _load_json_array(path)

    if sample_index < 0 or sample_index >= len(rows):
        raise SampleNoticeNotFoundError(
            f"sample_index {sample_index}를 찾을 수 없습니다."
        )

    row = rows[sample_index]
    raw_text = row.get("raw_text")
    if not isinstance(raw_text, str) or not raw_text.strip():
        raise SampleNoticeRawTextMissingError(
            f"sample_index {sample_index}에 사용 가능한 raw_text가 없습니다."
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
