"""업로드 파일을 로컬 디스크에 저장하는 유틸.

S3 전환 시 이 모듈만 교체하면 서비스/라우터는 그대로 둘 수 있도록,
저장 대상(디스크/버킷) 세부를 여기에 가둔다.
"""

import uuid
from pathlib import Path

from fastapi import UploadFile

# 한 번에 메모리로 올리지 않고 청크 단위로 흘려 쓰면서 크기 제한을 검사한다.
# 큰 파일을 통째로 read()하면 50MB가 그대로 메모리에 올라오므로 스트리밍한다.
_CHUNK_SIZE = 1024 * 1024  # 1MB


class FileTooLargeError(Exception):
    """업로드 파일이 허용 크기(max_bytes)를 초과했을 때."""

    def __init__(self, max_bytes: int):
        self.max_bytes = max_bytes
        super().__init__(f"업로드 파일이 최대 크기({max_bytes} bytes)를 초과했습니다")


async def save_upload_file(file: UploadFile, storage_root: str, max_bytes: int) -> str:
    """UploadFile을 storage_root 아래에 저장하고 저장 경로(str)를 반환한다.

    파일명은 원본 확장자를 유지한 uuid로 지어 충돌·경로 조작을 피한다
    (원본 확장자는 이후 OCR 단계에서 포맷 판별에 쓰인다). 크기 초과 시
    쓰다 만 파일을 지우고 FileTooLargeError를 던진다.
    """
    suffix = Path(file.filename or "").suffix.lower()
    dest_dir = Path(storage_root)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{uuid.uuid4().hex}{suffix}"

    size = 0
    try:
        with dest.open("wb") as out:
            while chunk := await file.read(_CHUNK_SIZE):
                size += len(chunk)
                if size > max_bytes:
                    raise FileTooLargeError(max_bytes)
                out.write(chunk)
    except BaseException:
        # 크기 초과든 다른 I/O 오류든, 쓰다 만 파일을 남기지 않는다.
        dest.unlink(missing_ok=True)
        raise

    return str(dest)


def delete_stored_file(ref: str) -> None:
    """save_upload_file이 반환한 저장 참조(ref)를 삭제한다.

    저장과 삭제를 같은 모듈에 두어, 저장소를 S3로 바꿀 때 여기(put/delete)만
    교체하면 서비스는 그대로 두게 한다. 이미 없는 파일은 조용히 넘어간다.
    """
    Path(ref).unlink(missing_ok=True)
