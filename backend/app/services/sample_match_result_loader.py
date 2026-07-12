"""매칭 스코어링 미구현 기간에 쓰는 샘플 평가 템플릿 로더.

sample_business_plan_loader/sample_notice_loader와 같은 data/ JSON 패턴.
공고는 FK(notice_id) 때문에 DB의 실제 notice 행을 쓰고, 이 파일은 거기에
입힐 평가값(점수·추천레벨·근거 텍스트·result_json)만 제공한다.
실제 스코어링 로직이 붙으면 이 로더와 JSON은 삭제한다.
"""

import json
from pathlib import Path
from typing import Any

_SAMPLE_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "match_result_samples.json"
)


class SampleMatchResultLoadError(Exception):
    """샘플 평가 템플릿 JSON을 읽거나 파싱할 수 없을 때 발생."""


def load_sample_match_results() -> list[dict[str, Any]]:
    """평가 템플릿 배열을 반환한다. 공고 수보다 적으면 호출부가 순환 적용한다."""
    try:
        payload = json.loads(_SAMPLE_PATH.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SampleMatchResultLoadError(
            f"샘플 평가 JSON을 읽을 수 없습니다: {_SAMPLE_PATH}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise SampleMatchResultLoadError(
            f"샘플 평가 JSON을 파싱할 수 없습니다: {_SAMPLE_PATH}"
        ) from exc

    if not isinstance(payload, list) or not payload:
        raise SampleMatchResultLoadError(
            "샘플 평가 JSON은 비어있지 않은 배열이어야 합니다."
        )
    for row in payload:
        if not isinstance(row, dict):
            raise SampleMatchResultLoadError(
                "샘플 평가 JSON의 각 항목은 객체여야 합니다."
            )
    return payload
