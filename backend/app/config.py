from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    gemini_api_key: str = ""
    serpapi_key: str = ""
    google_books_api_key: str = ""
    openai_api_key: str = ""

    backend_host: str = "0.0.0.0"
    backend_port: int = 8000
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    default_country: str = "US"
    default_currency: str = "USD"

    # Vision: use the flash-lite that's actually serving (3.6 is 503-overloaded on free tier).
    gemini_vision_model: str = "gemini-3.5-flash-lite"
    gemini_agent_model: str = "gemini-3.5-flash-lite"
    gemini_live_model: str = "gemini-3.5-flash-lite"

    # Pricing thresholds
    appraisal_threshold_usd: float = 300.0

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
