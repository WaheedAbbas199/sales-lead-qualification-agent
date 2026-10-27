"""Application settings, validated at startup (12-factor, environment driven)."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

INSECURE_SECRETS = {"", "CHANGE_ME_TO_A_LONG_RANDOM_VALUE", "changeme", "secret"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: Literal["development", "test", "production"] = "development"
    app_name: str = "Sales Lead Qualification Agent"
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"
    log_json: bool = True

    database_url: str = "sqlite:///./data/app.db"

    secret_key: str = "CHANGE_ME_TO_A_LONG_RANDOM_VALUE"
    access_token_minutes: int = 60
    allowed_origins: str = "http://localhost:8000,http://127.0.0.1:8000"
    login_max_attempts: int = 5
    login_window_seconds: int = 300

    llm_provider: Literal["disabled", "gemini"] = "disabled"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    llm_timeout_seconds: int = 45
    llm_max_retries: int = Field(2, ge=0, le=5)
    llm_max_input_chars: int = Field(6000, ge=500)

    research_enabled: bool = False
    search_provider: Literal["brave", "tavily"] = "brave"
    brave_api_key: str = ""
    tavily_api_key: str = ""

    workflow_inline: bool = False
    workflow_stale_minutes: int = 15
    csv_max_bytes: int = 2_000_000
    csv_max_rows: int = 2000

    email_sending_enabled: bool = False
    enable_docs: bool = True

    @property
    def origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def llm_configured(self) -> bool:
        return self.llm_provider == "gemini" and bool(self.gemini_api_key)

    @property
    def research_configured(self) -> bool:
     if not self.research_enabled:
        return False

     if self.search_provider == "tavily":
        return bool(self.tavily_api_key)

     return bool(self.brave_api_key)

    @model_validator(mode="after")
    def _validate_security(self) -> "Settings":
        if self.is_production:
            if self.secret_key in INSECURE_SECRETS or len(self.secret_key) < 32:
                raise ValueError("SECRET_KEY must be a random value of at least 32 chars in production")
            if "*" in self.origins:
                raise ValueError("ALLOWED_ORIGINS must not contain '*' in production")
        if self.llm_provider == "gemini" and not self.gemini_api_key:
            # Not fatal: the app reports AI as 'not configured' instead of pretending it works.
            pass
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
