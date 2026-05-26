from fastapi import APIRouter
from app.api.routes import auth, scenarios, sessions, admin, ingestion, slack

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(scenarios.router)
api_router.include_router(sessions.router)
api_router.include_router(admin.router)
api_router.include_router(ingestion.router)
api_router.include_router(slack.router)
