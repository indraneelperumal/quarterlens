from __future__ import annotations

from app.config import Settings


def test_tavily_api_key_loads_from_env(monkeypatch) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", "tavily-test-key")

    loaded = Settings()

    assert loaded.tavily_api_key == "tavily-test-key"
