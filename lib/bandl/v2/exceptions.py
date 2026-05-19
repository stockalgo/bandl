"""Bandl V2 exception hierarchy."""


class BandlError(Exception):
    """Base error for all Bandl failures."""


class ProviderError(BandlError):
    """Error raised by a specific provider."""

    def __init__(
        self,
        provider: str,
        message: str,
        *,
        code: str | None = None,
        retryable: bool = False,
    ) -> None:
        self.provider = provider
        self.code = code
        self.retryable = retryable
        super().__init__(f"[{provider}] {message}")


class SymbolNotFoundError(BandlError):
    """Symbol unknown or unsupported for the requested provider."""


class RateLimitError(ProviderError):
    """Rate limit exceeded on upstream API."""


class AuthenticationError(ProviderError):
    """Authentication failed or credentials are missing."""


class GeoRestrictionError(ProviderError):
    """Upstream API blocked the request based on client location (HTTP 451)."""


class DataNotAvailableError(BandlError):
    """Requested data is not available for the given range or instrument."""


class ConfigurationError(BandlError):
    """Client or provider configuration is invalid."""
