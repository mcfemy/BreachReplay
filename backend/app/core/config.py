from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    DATABASE_URL: str
    SYNC_DATABASE_URL: str

    ANTHROPIC_API_KEY: str
    CLAUDE_MODEL: str = "claude-sonnet-4-6"

    GEMINI_API_KEY: Optional[str] = None
    GEMINI_MODEL: str = "gemini-2.5-flash"

    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    REDIS_URL: str = "redis://localhost:6379/0"

    AWS_ACCESS_KEY_ID: Optional[str] = None
    AWS_SECRET_ACCESS_KEY: Optional[str] = None
    AWS_REGION: str = "us-east-1"
    S3_BUCKET: str = "breachreplay-documents"

    SENDGRID_API_KEY: Optional[str] = None
    FROM_EMAIL: str = "noreply@breachreplay.com"

    SENTRY_DSN: Optional[str] = None

    SUPABASE_URL: Optional[str] = None
    SUPABASE_ANON_KEY: Optional[str] = None

    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    PASSWORD_RESET_EXPIRE_MINUTES: int = 15
    FRONTEND_URL: str = "http://localhost:5173"

    SLACK_WEBHOOK_URL: Optional[str] = None
    SLACK_SIGNING_SECRET: Optional[str] = None
    SLACK_CHANNEL_ID: Optional[str] = None

    GOOGLE_CLIENT_ID: Optional[str] = None
    GOOGLE_CLIENT_SECRET: Optional[str] = None

    MICROSOFT_CLIENT_ID: Optional[str] = None
    MICROSOFT_CLIENT_SECRET: Optional[str] = None
    MICROSOFT_TENANT_ID: str = "common"

    GITHUB_CLIENT_ID: Optional[str] = None
    GITHUB_CLIENT_SECRET: Optional[str] = None

    AI_PREFER_GEMINI: bool = False

    STRIPE_SECRET_KEY: Optional[str] = None
    STRIPE_WEBHOOK_SECRET: Optional[str] = None
    STRIPE_PRICE_ID_ENTERPRISE: Optional[str] = None
    STRIPE_PUBLISHABLE_KEY: Optional[str] = None

    SIEM_WEBHOOK_TIMEOUT: int = 5

    ENVIRONMENT: str = "development"
    DEBUG: bool = False

    class Config:
        env_file = ".env"


settings = Settings()
