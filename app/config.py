from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Centralized app configuration, sourced from environment variables / .env.

    Nothing here is hardcoded in source: secrets (VAPI_API_KEY, VAPI_WEBHOOK_SECRET)
    are only ever read from the environment, per the assessment's security requirement.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "sqlite:///./patients.db"

    vapi_api_key: str = ""
    vapi_webhook_secret: str = ""
    public_base_url: str = "http://localhost:8000"

    log_level: str = "INFO"
    port: int = 8000


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
