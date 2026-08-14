from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    APP_NAME: str = "PlayNexis"

    APP_ENV: str = "development"

    # Optional at app bootstrap. Enforced only when SQLAlchemy layer is used.
    DATABASE_URL: Optional[str] = None

    SUPABASE_URL: str
    SUPABASE_KEY: str

    JWT_SECRET_KEY: str

    FRONTEND_URL: str = "http://localhost:5173"
    BACKEND_URL: str = "http://127.0.0.1:8000"
    ARENA_MEDIA_BUCKET: str = "Playnexis"

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )


settings = Settings()
