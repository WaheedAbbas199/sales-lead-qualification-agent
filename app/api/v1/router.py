from fastapi import APIRouter

from app.api.v1.endpoints import auth, dashboard, icp, leads, outreach, qualification, system

api_router = APIRouter()
for module in (system, auth, leads, qualification, icp, outreach, dashboard):
    api_router.include_router(module.router)
