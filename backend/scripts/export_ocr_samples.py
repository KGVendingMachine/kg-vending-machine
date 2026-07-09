"""backend/data/samples의 실제 사업계획서 파일을 OCR/텍스트 추출 파이프라인으로
돌려서, AI 팀원에게 전달할 샘플 데이터(JSON)를 만든다.

business_plan 테이블에 실제로 넣지 않고 JSON으로 뽑는 이유: backend/data/는
개인정보가 담긴 실제 지원자 파일이라 .gitignore로 막혀 있고, 팀원마다 로컬
DB가 따로 있어 DB로 공유할 수 없다. 결과 JSON(backend/data/ocr_samples.json)도
같은 이유로 data/ 밑에 두고 git이 아닌 Slack/드라이브 등으로 직접 전달한다.

실행: uv run python scripts/export_ocr_samples.py
"""

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from app.ocr.extract import extract_text

_SAMPLES_DIR = Path(__file__).resolve().parent.parent / "data" / "samples"
_OUTPUT_PATH = _SAMPLES_DIR.parent / "ocr_samples.json"
_SUPPORTED_SUFFIXES = {".pdf", ".hwp", ".hwpx", ".jpg", ".jpeg", ".png", ".tiff"}


async def _build_sample(file_path: Path) -> dict:
    text, file_type = await extract_text(str(file_path))
    return {
        "file_name": file_path.name,
        "file_type": file_type,
        "char_count": len(text),
        "raw_text": text,
        "extracted_at": datetime.now(timezone.utc).isoformat(),
    }


async def main() -> None:
    files = sorted(
        p for p in _SAMPLES_DIR.iterdir() if p.suffix.lower() in _SUPPORTED_SUFFIXES
    )
    if not files:
        print(f"{_SAMPLES_DIR}에 지원 형식 파일이 없습니다.")
        return

    samples = []
    for file_path in files:
        print(f"추출 중: {file_path.name}")
        try:
            samples.append(await _build_sample(file_path))
        except Exception as exc:
            print(f"  실패: {exc}")

    _OUTPUT_PATH.write_text(
        json.dumps(samples, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"{len(samples)}건 저장 완료: {_OUTPUT_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
