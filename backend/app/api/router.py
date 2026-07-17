from fastapi import APIRouter
from app.api.business_plan import router as business_plan_router
from app.api.business_plan_analysis import router as business_plan_analysis_router
from app.api.match_log import router as match_log_router
from app.api.business_plan_samples import router as business_plan_samples_router
from app.api.notice import router as notice_router
from app.api.notice_collection import router as notice_collection_router
from app.api.notice_embedding import router as notice_embedding_router
from app.api.notice_embedding_backlog import router as notice_embedding_backlog_router
from app.api.notice_normalization import router as notice_normalization_router
from app.api.notice_normalization_backlog import (
    router as notice_normalization_backlog_router,
)
from app.api.notice_samples import router as notice_samples_router
from app.api.notice_ocr import router as notice_ocr_router
from app.api.notice_attachment_precollection import (
    router as notice_attachment_precollection_router,
)
from app.api.bookmark import router as bookmark_router
from app.api.notice_eligibility import router as notice_eligibility_router

from app.api import auth, company_profile

api_router = APIRouter()

api_router.include_router(business_plan_samples_router)
api_router.include_router(notice_samples_router)
api_router.include_router(business_plan_router)
api_router.include_router(business_plan_analysis_router)
api_router.include_router(match_log_router)
api_router.include_router(notice_router)
api_router.include_router(notice_collection_router)
api_router.include_router(notice_ocr_router)
api_router.include_router(notice_attachment_precollection_router)
api_router.include_router(notice_embedding_router)
api_router.include_router(notice_embedding_backlog_router)
api_router.include_router(notice_normalization_router)
api_router.include_router(notice_normalization_backlog_router)
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(company_profile.router)
api_router.include_router(bookmark_router)
api_router.include_router(notice_eligibility_router)
