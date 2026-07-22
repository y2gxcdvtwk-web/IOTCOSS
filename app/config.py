from functools import lru_cache
from pathlib import Path

from pydantic import ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Mobius AI Gateway"
    environment: str = "development"
    api_prefix: str = "/api/v1"
    database_path: Path = Path("./data/app.db")
    session_ttl_seconds: int = 86_400
    cors_origins: str = "http://localhost:3000,http://localhost:5173"

    mobius_base_url: str = "https://platform.iotcoss.ac.kr/api/proxy/swagger/Mobius"
    mobius_origin: str = "S"
    mobius_ae_id: str = ""
    mobius_timeout_seconds: float = 10
    mobius_auto_register: bool = True
    mobius_api_key: str = "REDACTED_MOBIUS_API_KEY_00000000"
    mobius_lecture: str = "LCT_20260002"
    mobius_creator: str = "sjuADDHD"
    mobius_notification_uri: str = ""
    mobius_subscription_name: str = "subToAnalyticsServer"
    mobius_sync_on_startup: bool = True

    ai_provider: str = "local"
    ai_model: str = "gpt-4.1-mini"
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"

    @field_validator("mobius_api_key", "mobius_lecture", "mobius_creator", mode="before")
    @classmethod
    def keep_fixed_mobius_credentials(
        cls, value: str | None, info: ValidationInfo
    ) -> str:
        fixed = {
            "mobius_api_key": "REDACTED_MOBIUS_API_KEY_00000000",
            "mobius_lecture": "LCT_20260002",
            "mobius_creator": "sjuADDHD",
        }
        return value or fixed[info.field_name]

    @property
    def allowed_origins(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()

