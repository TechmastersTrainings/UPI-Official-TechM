from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All configuration comes from environment variables (or backend/.env in development)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    APP_NAME: str = "TechMasters Payment Gateway"
    APP_ENV: Literal["development", "test", "staging", "production"] = "development"
    LOG_LEVEL: str = "INFO"

    # Database. Production target: Aiven MySQL 8, e.g.
    # mysql+pymysql://user:pass@host:port/techmasters_pg?charset=utf8mb4
    DATABASE_URL: str = "sqlite:///./techmasters_dev.db"
    DATABASE_SSL_CA: str | None = None  # path to Aiven ca.pem; enables TLS with verification
    DATABASE_POOL_SIZE: int = 10
    DATABASE_MAX_OVERFLOW: int = 10
    DATABASE_POOL_RECYCLE: int = 280  # below MySQL wait_timeout on managed services

    REDIS_URL: str | None = "redis://localhost:6379/0"

    # Secrets — no defaults in production (validated below).
    JWT_SECRET: str = Field(default="", repr=False)
    JWT_ALGORITHM: str = "HS256"
    JWT_ISSUER: str = "techmasters-pg"
    ACCESS_TOKEN_TTL_SECONDS: int = 900
    REFRESH_TOKEN_TTL_SECONDS: int = 60 * 60 * 24 * 7
    # Comma-separated Fernet keys, newest first. Generate: python -m app.cli generate-key
    ENCRYPTION_KEYS: str = Field(default="", repr=False)
    # Pepper for API-secret / refresh-token HMAC hashing.
    HASH_PEPPER: str = Field(default="", repr=False)

    CORS_ORIGINS: str = "http://localhost:5177"
    FRONTEND_BASE_URL: str = "http://localhost:5177"
    COOKIE_SECURE: bool = False
    COOKIE_DOMAIN: str | None = None

    # Day/month boundaries for reports. India Standard Time has no DST, so a fixed offset is exact.
    REPORTING_UTC_OFFSET_MINUTES: int = 330

    LOGIN_MAX_FAILED_ATTEMPTS: int = 5
    LOGIN_LOCKOUT_SECONDS: int = 900
    LOGIN_RATE_LIMIT_PER_MINUTE: int = 10

    # Gateway API (/api/v1)
    API_RATE_LIMIT_PER_MINUTE: int = 300  # per API key
    API_AUTH_FAILURES_PER_MINUTE: int = 20  # per client IP

    # Payments. Amounts are in paise. The default ceiling is the standard UPI per-transaction
    # limit (₹1,00,000); raise it only for merchant categories the provider allows higher limits for.
    PAYMENT_MIN_AMOUNT: int = 100
    PAYMENT_MAX_AMOUNT: int = 10_000_000
    PAYMENT_DEFAULT_EXPIRY_SECONDS: int = 900
    PAYMENT_MIN_EXPIRY_SECONDS: int = 60
    PAYMENT_MAX_EXPIRY_SECONDS: int = 86_400

    # Hosted checkout. Links are {CHECKOUT_BASE_URL}/{token}; defaults to the console's /checkout route.
    CHECKOUT_BASE_URL: str = ""
    CHECKOUT_RATE_LIMIT_PER_MINUTE: int = 120  # per client IP, public checkout endpoints

    CALLBACK_RATE_LIMIT_PER_MINUTE: int = 600  # per source IP, provider callbacks

    # Sandbox simulator: delay before amount-based test outcomes are decided.
    SANDBOX_AUTO_OUTCOME_SECONDS: int = 8

    # Background worker (python -m app.workers)
    WORKER_INTERVAL_SECONDS: int = 15

    @field_validator("DATABASE_SSL_CA", "COOKIE_DOMAIN", "REDIS_URL", mode="before")
    @classmethod
    def _blank_to_none(cls, v):
        return v or None

    @model_validator(mode="after")
    def _require_secrets_outside_dev(self):
        if self.APP_ENV in ("staging", "production"):
            missing = [k for k in ("JWT_SECRET", "ENCRYPTION_KEYS", "HASH_PEPPER") if not getattr(self, k)]
            if missing:
                raise ValueError(f"Missing required secrets: {', '.join(missing)}")
            if len(self.JWT_SECRET) < 32:
                raise ValueError("JWT_SECRET must be at least 32 characters")
            if self.DATABASE_URL.startswith("sqlite"):
                raise ValueError("SQLite is not allowed outside development/test")
            if not self.COOKIE_SECURE:
                raise ValueError("COOKIE_SECURE must be true outside development/test")
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def checkout_base_url(self) -> str:
        return (self.CHECKOUT_BASE_URL or self.FRONTEND_BASE_URL.rstrip("/") + "/checkout").rstrip("/")

    @property
    def is_dev_like(self) -> bool:
        return self.APP_ENV in ("development", "test")


@lru_cache
def get_settings() -> Settings:
    return Settings()
