from functools import lru_cache
from pathlib import Path

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
    mobius_api_key: str = ""
    mobius_lecture: str = ""
    mobius_creator: str = ""
    mobius_notification_uri: str = ""
    mobius_subscription_name: str = "subToAnalyticsServer"

    ai_provider: str = "local"
    ai_model: str = "gpt-4.1-mini"
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"

    @property
    def allowed_origins(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()

