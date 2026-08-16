"""
Application settings — loaded from environment variables.
"""
from functools import lru_cache
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # ── Application ───────────────────────────────────────────────────────────
    BRACK_ENV: str = "development"
    BRACK_BASE_URL: str = "http://localhost:3000"
    BRACK_API_URL: str = "http://localhost:8000"
    BRACK_SECRET_KEY: str = "brack-development-secret-key-change-in-prod"
    BRACK_JWT_SECRET: str = "brack-jwt-development-secret-change-in-prod"
    BRACK_JWT_ALGORITHM: str = "HS256"
    BRACK_JWT_EXPIRE_MINUTES: int = 10080  # 7 days
    BRACK_ALLOW_REGISTRATION: bool = True

    # ── Database ──────────────────────────────────────────────────────────────
    # Defaults to SQLite for immediate zero-config local running;
    # in Docker/Production, set DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/brack
    DATABASE_URL: str = "sqlite+aiosqlite:///./brack.db"
    POSTGRES_USER: str = "brack"
    POSTGRES_PASSWORD: str = "brackpassword"
    POSTGRES_DB: str = "brack"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432

    # ── Redis ─────────────────────────────────────────────────────────────────
    REDIS_URL: Optional[str] = None

    # ── Storage ───────────────────────────────────────────────────────────────
    BRACK_STORAGE_PATH: str = "./storage/repos"
    BRACK_UPLOAD_MAX_MB: int = 100

    # ── CORS ──────────────────────────────────────────────────────────────────
    BRACK_CORS_ORIGINS: str = "http://localhost:3000,http://127.0.0.1:3000"

    # ── Rate Limiting ─────────────────────────────────────────────────────────
    BRACK_RATE_LIMIT_PER_MINUTE: int = 100

    # ── AI (Phase 3) ──────────────────────────────────────────────────────────
    AI_PROVIDER: Optional[str] = None
    AI_MODEL: Optional[str] = None
    AI_API_KEY: Optional[str] = None

    # ── Logging ───────────────────────────────────────────────────────────────
    LOG_LEVEL: str = "INFO"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.BRACK_CORS_ORIGINS.split(",")]

    @property
    def is_production(self) -> bool:
        return self.BRACK_ENV == "production"

    @property
    def async_database_url(self) -> str:
        """Ensure the URL uses asyncpg driver if postgresql."""
        url = self.DATABASE_URL
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return url


@lru_cache
def get_settings() -> Settings:
    return Settings()
