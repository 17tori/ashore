from functools import lru_cache
from typing import Literal

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. Every value comes from the environment (see .env.example)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: Literal["development", "test", "production"] = "development"
    app_name: str = "Ashore Careers"
    public_base_url: str = "http://localhost:3000"
    log_level: str = "INFO"

    database_url: str = "postgresql+asyncpg://ashore:ashore@localhost:5432/ashore"
    redis_url: str = "redis://localhost:6379/0"

    # 32-byte keys, urlsafe base64. The first key encrypts, all keys decrypt (rotation).
    encryption_keys: SecretStr = SecretStr("")
    session_ttl_hours: int = 24 * 14
    cookie_secure: bool = False

    upload_max_bytes: int = 5 * 1024 * 1024

    # hh.ru
    hh_client_id: str = ""
    hh_client_secret: SecretStr = SecretStr("")
    hh_app_access_token: SecretStr = SecretStr("")
    hh_user_agent: str = ""
    hh_api_base_url: str = "https://api.hh.ru"
    hh_authorize_url: str = "https://hh.ru/oauth/authorize"
    hh_token_url: str = "https://api.hh.ru/token"
    hh_requests_per_second: float = 2.0
    hh_timeout_seconds: float = 15.0
    hh_max_retries: int = 3
    hh_circuit_failure_threshold: int = 5
    hh_circuit_cooldown_seconds: int = 15 * 60
    hh_resume_publish_interval_hours: int = 4

    # AI
    ai_provider: Literal["local", "openai_compatible", "anthropic"] = "local"
    ai_base_url: str = ""
    ai_api_key: SecretStr = SecretStr("")
    ai_model: str = ""
    ai_embeddings_model: str = ""
    ai_timeout_seconds: float = 60.0
    ai_price_input_per_1k: float = 0.0
    ai_price_output_per_1k: float = 0.0

    # Telegram
    telegram_bot_token: SecretStr = SecretStr("")
    telegram_bot_username: str = ""
    telegram_webhook_secret: SecretStr = SecretStr("")

    # Scheduler
    scheduler_tick_seconds: int = 300
    worker_max_jobs: int = 4

    demo_mode: bool = False

    @field_validator("public_base_url")
    @classmethod
    def strip_slash(cls, v: str) -> str:
        return v.rstrip("/")

    @property
    def hh_redirect_uri(self) -> str:
        return f"{self.public_base_url}/api/hh/oauth/callback"

    @property
    def hh_configured(self) -> bool:
        return bool(self.hh_client_id and self.hh_client_secret.get_secret_value() and self.hh_user_agent)

    @property
    def telegram_configured(self) -> bool:
        return bool(self.telegram_bot_token.get_secret_value())

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    def encryption_key_list(self) -> list[str]:
        return [k.strip() for k in self.encryption_keys.get_secret_value().split(",") if k.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
