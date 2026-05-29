from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Monorepo root .env (works when uvicorn runs from apps/api)
_REPO_ROOT = Path(__file__).resolve().parents[3]
_ENV_FILES = (
    _REPO_ROOT / ".env",
    Path(".env"),  # apps/api/.env override
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=[str(p) for p in _ENV_FILES if p.exists()] or ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    anthropic_api_key: str = ""
    fmp_api_key: str = ""
    alpha_vantage_api_key: str = ""
    sec_edgar_user_agent: str = "EarningsAgent contact@example.com"

    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "financial_docs"

    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: str = "http://localhost:3000"

    # MVP watchlist — expand after v0
    default_watchlist: list[str] = [
        "AAPL",
        "GOOGL",
        "MSFT",
        "NVDA",
        "AMZN",
        "JPM",
        "UNH",
        "XOM",
        "COST",
    ]

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
