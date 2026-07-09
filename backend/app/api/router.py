from fastapi import APIRouter
from app.api.business_plan import router as business_plan_router
from app.api.notice import router as notice_router
from app.api.notice_collection import router as notice_collection_router

from app.api import auth

api_router = APIRouter()

api_router.include_router(business_plan_router)
api_router.include_router(notice_router)
api_router.include_router(notice_collection_router)
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
