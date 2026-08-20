from urllib.parse import urlparse

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    APP_NAME: str = "PlayNexis"

    APP_ENV: str = "development"

    # Optional at app bootstrap. Enforced only when SQLAlchemy layer is used.
    DATABASE_URL: Optional[str] = None

    SUPABASE_URL: str
    SUPABASE_ANON_KEY: Optional[str] = None
    SUPABASE_SERVICE_KEY: Optional[str] = None
    SUPABASE_KEY: Optional[str] = None

    JWT_SECRET_KEY: str

    FRONTEND_URL: str = "http://localhost:5173"
    BACKEND_URL: str = "http://127.0.0.1:8000"
    ARENA_MEDIA_BUCKET: str = "Playnexis"

    SMTP_HOST: Optional[str] = None
    SMTP_PORT: int = 587
    SMTP_USERNAME: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None
    SMTP_FROM_EMAIL: Optional[str] = None
    SMTP_FROM_NAME: str = "PLAYNEXIS"
    SMTP_USE_TLS: bool = True
    SMTP_USE_SSL: bool = False
    EMAIL_VERIFICATION_TOKEN_TTL_SECONDS: int = 86400

    @field_validator("FRONTEND_URL", "BACKEND_URL", mode="before")
    @classmethod
    def normalize_application_url(cls, value):
        raw_url = str(value or "").strip().rstrip("/")
        if not raw_url:
            raise ValueError("Application URLs cannot be empty")

        if "://" not in raw_url:
            hostname = raw_url.split("/", 1)[0].split(":", 1)[0].lower()
            scheme = "http" if hostname in {"localhost", "127.0.0.1", "::1"} else "https"
            raw_url = f"{scheme}://{raw_url}"

        parsed = urlparse(raw_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Application URLs must be valid HTTP(S) URLs")
        if parsed.query or parsed.fragment:
            raise ValueError("Application URLs cannot contain a query string or fragment")

        return raw_url

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )


settings = Settings()
