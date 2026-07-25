"""Run sample normalization and write a quality report.

This is a local QA helper for the AI normalization pipeline. It reads OCR sample
JSON files under backend/data, calls the same LLM normalizers used by the API,
validates the normalized output, and writes a compact report that can be used to
decide prompt/post-processing improvements before matching work starts.

Run:
    uv run python scripts/evaluate_normalization_quality.py --kind both --limit 30
"""

import argparse
import asyncio
import json
import sys
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from app.ai.normalizer import AiNormalizationError, normalize_text
from app.ai.notice_normalizer import normalize_notice_text
from app.schemas.business_plan import ValidationResult
from app.schemas.notice_normalization import NormalizedNoticeSchema
from app.services.business_plan_service import validate_normalized
from app.services.notice_normalization_helpers import (
    build_notice_prompt_text,
    enrich_normalized_notice,
)
from app.services.notice_service import validate_normalized_notice
from app.services.sample_business_plan_loader import load_sample_business_plan
from app.services.sample_notice_loader import load_sample_notice

_BACKEND_DIR = Path(__file__).resolve().parent.parent
_DEFAULT_BUSINESS_PLAN_PATH = _BACKEND_DIR / "data" / "ocr_samples.json"
_DEFAULT_NOTICE_PATH = _BACKEND_DIR / "data" / "notice_ocr_samples.json"
_DEFAULT_OUTPUT_PATH = _BACKEND_DIR / "data" / "normalization_quality_report.json"


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _counter_to_dict(counter: Counter[str]) -> dict[str, int]:
    return dict(sorted(counter.items(), key=lambda item: (-item[1], item[0])))


def _validation_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    missing_counter: Counter[str] = Counter()
    error_counter: Counter[str] = Counter()
    completed = 0
    valid = 0

    for result in results:
        if result["status"] != "completed":
            continue
        completed += 1
        validation = result["validation_result"]
        if validation["is_valid"]:
            valid += 1
        missing_counter.update(validation["missing_required_fields"])
        error_counter.update(validation.get("errors", []))

    return {
        "total": len(results),
        "completed": completed,
        "failed": len(results) - completed,
        "valid": valid,
        "invalid": completed - valid,
        "missing_required_fields": _counter_to_dict(missing_counter),
        "validation_errors": _counter_to_dict(error_counter),
    }


def _validation_to_dict(validation: ValidationResult) -> dict[str, Any]:
    return validation.model_dump(mode="json")


async def _evaluate_business_plans(path: Path, limit: int) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for index in range(limit):
        try:
            sample = load_sample_business_plan(index, str(path))
        except Exception:  # noqa: BLE001
            if index == 0:
                raise
            break

        print(f"[business_plan] normalizing sample_index={index} {sample.file_name}")
        started_at = datetime.now(timezone.utc)
        try:
            normalized = await normalize_text(sample.raw_text)
            validation = validate_normalized(normalized)
        except AiNormalizationError as exc:
            results.append(
                {
                    "sample_index": index,
                    "file_name": sample.file_name,
                    "char_count": sample.char_count,
                    "status": "failed",
                    "error_message": str(exc),
                    "duration_seconds": (
                        datetime.now(timezone.utc) - started_at
                    ).total_seconds(),
                }
            )
            continue

        results.append(
            {
                "sample_index": index,
                "file_name": sample.file_name,
                "char_count": sample.char_count,
                "status": "completed",
                "validation_result": _validation_to_dict(validation),
                "duration_seconds": (
                    datetime.now(timezone.utc) - started_at
                ).total_seconds(),
                "normalized_preview": {
                    "company_name": normalized.company.name,
                    "industry": normalized.company.industry,
                    "solution_summary": normalized.solution.summary,
                    "scale_up_strategy": normalized.funding.scale_up_strategy,
                    "team_capabilities": normalized.team.capabilities,
                },
            }
        )
    return results


def _build_notice_sample_prompt(sample) -> str:
    return build_notice_prompt_text(
        label="샘플",
        metadata={
            "sample_index": str(sample.sample_index),
            "title": sample.title or "",
            "source": sample.source or "",
            "category": sample.category or "",
            "status": sample.status or "",
            "application_start_date": sample.application_start_date or "",
            "application_end_date": sample.application_end_date or "",
            "file_name": sample.file_name or "",
            "file_type": sample.file_type or "",
        },
        raw_text=sample.raw_text,
    )


def _enrich_notice_sample(sample, normalized: NormalizedNoticeSchema):
    return enrich_normalized_notice(
        normalized,
        title=sample.title,
        source=sample.source,
        category=sample.category,
        status=sample.status,
        application_start_date=_parse_date(sample.application_start_date),
        application_end_date=_parse_date(sample.application_end_date),
        raw_text=sample.raw_text,
    )


async def _evaluate_notices(path: Path, limit: int) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    sample_path = path.name if path.parent.name == "data" else str(path)
    for index in range(limit):
        try:
            sample = load_sample_notice(index, sample_path)
        except Exception:  # noqa: BLE001
            if index == 0:
                raise
            break

        print(f"[notice] normalizing sample_index={index} {sample.file_name}")
        started_at = datetime.now(timezone.utc)
        try:
            normalized = await normalize_notice_text(
                _build_notice_sample_prompt(sample)
            )
            normalized = _enrich_notice_sample(sample, normalized)
            validation = validate_normalized_notice(
                normalized, source_text=sample.raw_text
            )
        except AiNormalizationError as exc:
            results.append(
                {
                    "sample_index": index,
                    "title": sample.title,
                    "file_name": sample.file_name,
                    "char_count": sample.char_count,
                    "status": "failed",
                    "error_message": str(exc),
                    "duration_seconds": (
                        datetime.now(timezone.utc) - started_at
                    ).total_seconds(),
                }
            )
            continue

        results.append(
            {
                "sample_index": index,
                "title": sample.title,
                "file_name": sample.file_name,
                "char_count": sample.char_count,
                "status": "completed",
                "validation_result": _validation_to_dict(validation),
                "duration_seconds": (
                    datetime.now(timezone.utc) - started_at
                ).total_seconds(),
                "normalized_preview": {
                    "title": normalized.basic.title,
                    "category": normalized.basic.category,
                    "application_method": normalized.application.method,
                    "support_type": normalized.support.support_type,
                    "target_company_size": normalized.eligibility.target_company_size,
                    "matching_signals": normalized.matching.matching_signals,
                },
            }
        )
    return results


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--kind", choices=("business-plan", "notice", "both"), default="both"
    )
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument(
        "--business-plan-path", type=Path, default=_DEFAULT_BUSINESS_PLAN_PATH
    )
    parser.add_argument("--notice-path", type=Path, default=_DEFAULT_NOTICE_PATH)
    parser.add_argument("--output-path", type=Path, default=_DEFAULT_OUTPUT_PATH)
    args = parser.parse_args()

    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "limit": args.limit,
    }

    if args.kind in ("business-plan", "both"):
        business_plan_results = await _evaluate_business_plans(
            args.business_plan_path, args.limit
        )
        report["business_plan"] = {
            "summary": _validation_summary(business_plan_results),
            "items": business_plan_results,
        }

    if args.kind in ("notice", "both"):
        notice_results = await _evaluate_notices(args.notice_path, args.limit)
        report["notice"] = {
            "summary": _validation_summary(notice_results),
            "items": notice_results,
        }

    args.output_path.parent.mkdir(parents=True, exist_ok=True)
    args.output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"quality report saved: {args.output_path}")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    asyncio.run(main())
