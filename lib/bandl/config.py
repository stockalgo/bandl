"""Configuration types for Bandl."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ProviderSettings(BaseModel):
    """Per-provider options (keys, timeouts, overrides)."""

    model_config = ConfigDict(extra="forbid")

    api_key: str | None = Field(default=None, repr=False)
    api_secret: str | None = Field(default=None, repr=False)
    access_token: str | None = Field(default=None, repr=False)
    base_url: str | None = None


class BandlConfig(BaseModel):
    """Top-level client configuration."""

    timeout_seconds: float = Field(default=30.0, ge=1.0)
    max_http_retries: int = Field(default=3, ge=0)
    user_agent: str = Field(default="bandl/0.4 (+https://github.com/stockalgo/bandl)")

    # default provider ids per facet
    default_crypto_provider: str = "binance"
    default_equity_provider: str = "zerodha"

    providers: dict[str, ProviderSettings] = Field(default_factory=dict)
