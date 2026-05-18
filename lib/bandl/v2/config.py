"""Configuration types for Bandl V2."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ProviderSettings(BaseModel):
    """Per-provider options (keys, timeouts, overrides)."""

    api_key: str | None = None
    api_secret: str | None = None
    access_token: str | None = None
    base_url: str | None = None
    model_config = {"extra": "allow"}


class BandlConfig(BaseModel):
    """Top-level client configuration."""

    timeout_seconds: float = Field(default=30.0, ge=1.0)
    max_http_retries: int = Field(default=3, ge=0)
    user_agent: str = Field(default="bandl/0.2 (+https://github.com/stockalgo/bandl)")

    # default provider ids per facet
    default_crypto_provider: str = "binance"
    default_equity_provider: str = "zerodha"

    providers: dict[str, ProviderSettings] = Field(default_factory=dict)
