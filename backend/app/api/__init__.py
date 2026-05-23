from fastapi import APIRouter
from app.api.routes import auth, scenarios, sessions

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(scenarios.router)
api_router.include_router(sessions.router)
