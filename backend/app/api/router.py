from fastapi import APIRouter
from app.api.business_plan import router as business_plan_router

api_router = APIRouter()

api_router.include_router(business_plan_router)