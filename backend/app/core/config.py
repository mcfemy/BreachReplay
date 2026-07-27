from pydantic import field_validator
from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    DATABASE_URL: str
    SYNC_DATABASE_URL: str

    ANTHROPIC_API_KEY: str
    CLAUDE_MODEL: str = "claude-sonnet-4-6"

    GEMINI_API_KEY: Optional[str] = None
    GEMINI_MODEL: str = "gemini-2.5-flash"

    # NVIDIA NIM (integrate.api.nvidia.com) — OpenAI-compatible endpoint,
    # alternate SCENARIO EXTRACTION backend only (see EXTRACTION_PROVIDER
    # below). Never used by generate_decision_commentary/
    # generate_debrief_report — those are runtime paths, untouched.
    NVIDIA_API_KEY: Optional[str] = None
    NVIDIA_MODEL: str = "nvidia/nemotron-3-super-120b-a12b"

    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    REDIS_URL: str = "redis://localhost:6379/0"

    AWS_ACCESS_KEY_ID: Optional[str] = None
    AWS_SECRET_ACCESS_KEY: Optional[str] = None
    AWS_REGION: str = "us-east-1"
    S3_BUCKET: str = "breachreplay-documents"

    @field_validator("AWS_REGION", mode="before")
    @classmethod
    def _blank_aws_region_falls_back_to_default(cls, v):
        """An AWS_REGION env var that's PRESENT but blank (e.g. a CI
        workflow declaring `AWS_REGION:` with no value, or an empty line in
        .env) still overrides this field's Python default with "" — pydantic
        only applies a field default when the env var is absent, not when
        it's empty. An empty region string then poisons every boto3 call
        that relies on it (S3, Bedrock, ...), so treat blank the same as
        unset."""
        if v is None or (isinstance(v, str) and v.strip() == ""):
            return "us-east-1"
        return v

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

    # MFA/TOTP: optional Fernet key for encrypting TOTP secrets at rest.
    # If unset, the key is derived from SECRET_KEY via HKDF.
    MFA_ENCRYPTION_KEY: Optional[str] = None

    AI_PREFER_GEMINI: bool = False
    # Scenario-extraction provider override (extract_scenario_from_document
    # only). "claude" (default) preserves the existing AI_PREFER_GEMINI
    # claude<->gemini fallback behavior untouched; "nemotron" routes
    # extraction through NVIDIA NIM instead, no fallback to Claude/Gemini —
    # a failed Nemotron extraction should surface as a failure, not
    # silently substitute a different model's output.
    #
    # KEEP THIS "claude" FOR REAL INGESTION. Verified against the actual
    # Colonial Pipeline source doc: Nemotron fabricated a recurring C2 IP
    # and other plausible-but-uncited artifacts across two independent runs,
    # and inverted one documented fact outright. "nemotron" is
    # candidate-generation only — every identifier it produces needs manual
    # source verification before use. Full findings:
    # docs/NEMOTRON_EXTRACTION_FINDINGS.md.
    EXTRACTION_PROVIDER: str = "claude"

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
