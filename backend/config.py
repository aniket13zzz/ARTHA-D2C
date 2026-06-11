"""
artha-v2/backend/config.py
Pydantic settings — reads from .env file.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Supabase
    SUPABASE_URL: str
    SUPABASE_SERVICE_ROLE_KEY: str
    SUPABASE_ANON_KEY: str

    # Encryption
    FERNET_KEY: str

    # Cron
    CRON_SECRET: str

    # Email
    RESEND_API_KEY: str
    RESEND_FROM_EMAIL: str = "alerts@artha.finance"

    # Razorpay billing
    RAZORPAY_BILLING_KEY_ID: str
    RAZORPAY_BILLING_KEY_SECRET: str

    # Sentry
    SENTRY_DSN: str = ""

    # App
    APP_ENV: str = "development"
    APP_VERSION: str = "2.0.0"
    FRONTEND_URL: str = "http://localhost:3000"
    LOG_LEVEL: str = "INFO"

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
