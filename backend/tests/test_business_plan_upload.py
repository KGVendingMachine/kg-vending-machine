"""
tests/test_business_plan_upload.py

POST /business-plans 업로드 흐름(services.business_plan_service.upload_business_plan)
테스트. HTTP 서버 없이 서비스 함수를 직접 호출한다. 파일 저장은 tmp_path로
격리해 실제 storage 디렉터리를 건드리지 않는다.
"""

import io
from pathlib import Path

import pytest
from fastapi import UploadFile

from app.models.company import CompanyProfile
from app.models.user import User
from app.repositories.business_plan_repository import get_by_id
from app.services.business_plan_service import (
    CompanyProfileRequiredError,
    UnsupportedFileTypeError,
    upload_business_plan,
)
from app.utils.file_storage import FileTooLargeError

pytestmark = pytest.mark.anyio


async def _primary_profile(db_session, user: User) -> CompanyProfile:
    """get_primary_by_user가 찾을 수 있도록 is_primary=True 프로필을 만든다."""
    profile = CompanyProfile(user_id=user.id, is_primary=True)
    db_session.add(profile)
    await db_session.flush()
    return profile


def _upload(filename: str, data: bytes) -> UploadFile:
    return UploadFile(filename=filename, file=io.BytesIO(data))


async def test_upload_saves_file_and_creates_row(db_session, test_user, tmp_path):
    profile = await _primary_profile(db_session, test_user)
    file = _upload("사업계획서.pdf", b"%PDF-1.4 fake content")

    plan = await upload_business_plan(
        db_session,
        user_id=test_user.id,
        file=file,
        storage_root=str(tmp_path),
        max_upload_size_bytes=1_000_000,
    )

    assert plan.id is not None
    assert plan.company_profile_id == profile.id
    assert plan.title == "사업계획서.pdf"
    assert plan.file_type == "PDF"
    assert Path(plan.file_url).exists()

    # commit까지 됐는지 재조회로 확인
    fetched = await get_by_id(db_session, plan.id)
    assert fetched is not None
    assert fetched.file_url == plan.file_url


async def test_upload_requires_company_profile(db_session, test_user, tmp_path):
    file = _upload("plan.pdf", b"data")

    with pytest.raises(CompanyProfileRequiredError):
        await upload_business_plan(
            db_session,
            user_id=test_user.id,
            file=file,
            storage_root=str(tmp_path),
            max_upload_size_bytes=1_000_000,
        )

    assert not list(tmp_path.iterdir())  # 파일도 저장되면 안 됨


async def test_upload_rejects_unsupported_extension(db_session, test_user, tmp_path):
    await _primary_profile(db_session, test_user)
    file = _upload("plan.docx", b"data")

    with pytest.raises(UnsupportedFileTypeError):
        await upload_business_plan(
            db_session,
            user_id=test_user.id,
            file=file,
            storage_root=str(tmp_path),
            max_upload_size_bytes=1_000_000,
        )

    assert not list(tmp_path.iterdir())


async def test_upload_rejects_file_exceeding_max_size(db_session, test_user, tmp_path):
    await _primary_profile(db_session, test_user)
    file = _upload("plan.pdf", b"x" * 2048)

    with pytest.raises(FileTooLargeError):
        await upload_business_plan(
            db_session,
            user_id=test_user.id,
            file=file,
            storage_root=str(tmp_path),
            max_upload_size_bytes=1024,
        )

    assert not list(tmp_path.iterdir())  # 쓰다 만 파일이 정리됐는지
