from fastapi import APIRouter
from app.api.routes import auth, scenarios, sessions, admin, ingestion, slack, billing, daily, redteam, profile, certs, orgs, teams

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(scenarios.router)
api_router.include_router(sessions.router)
api_router.include_router(admin.router)
api_router.include_router(ingestion.router)
api_router.include_router(slack.router)
api_router.include_router(billing.router)
api_router.include_router(daily.router)
api_router.include_router(redteam.router)
api_router.include_router(profile.router)
api_router.include_router(certs.router)
api_router.include_router(orgs.router)
api_router.include_router(teams.router)
