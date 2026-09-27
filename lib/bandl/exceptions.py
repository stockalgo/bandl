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

    def __init__(
        self,
        provider: str,
        message: str,
        *,
        code: str | None = None,
        retryable: bool = False,
        retry_after: float | None = None,
    ) -> None:
        self.retry_after = retry_after
        super().__init__(provider, message, code=code, retryable=retryable)


class AuthenticationError(ProviderError):
    """Authentication failed or credentials are missing."""


class GeoRestrictionError(ProviderError):
    """Upstream API blocked the request based on client location (HTTP 451)."""


class DataNotAvailableError(BandlError):
    """Requested data is not available for the given range or instrument."""


class ConfigurationError(BandlError):
    """Client or provider configuration is invalid."""


class UnsupportedCapabilityError(BandlError):
    """Provider does not support the requested account-history capability."""

    def __init__(self, provider: str, capability: str, *, message: str | None = None) -> None:
        self.provider = provider
        self.capability = capability
        msg = message or f"Provider '{provider}' does not support '{capability}'"
        super().__init__(msg)


class InvalidOrderError(ProviderError):
    """Client-side validation failure for an order request."""

    def __init__(
        self,
        provider: str,
        message: str,
        *,
        code: str | None = None,
    ) -> None:
        super().__init__(provider, message, code=code, retryable=False)


class OrderRejectedError(ProviderError):
    """Order placement, modification, or cancellation was rejected by the broker/OMS."""

    def __init__(
        self,
        provider: str,
        message: str,
        *,
        order_id: str | None = None,
        raw_status: str | None = None,
        code: str | None = None,
    ) -> None:
        self.order_id = order_id
        self.raw_status = raw_status
        super().__init__(provider, message, code=code, retryable=False)


class UncertainOutcomeError(ProviderError):
    """Mutation was dispatched, but network failure or 5xx left the outcome ambiguous."""

    def __init__(
        self,
        provider: str,
        message: str,
        *,
        operation: str | None = None,
        order_id: str | None = None,
        client_order_id: str | None = None,
        request_context: dict | None = None,
        code: str | None = None,
    ) -> None:
        self.operation = operation
        self.order_id = order_id
        self.client_order_id = client_order_id
        self.request_context = request_context or {}
        super().__init__(provider, message, code=code, retryable=False)


class InsufficientFundsError(ProviderError):
    """Margin or balance deficit for order execution."""

    def __init__(
        self,
        provider: str,
        message: str,
        *,
        code: str | None = None,
    ) -> None:
        super().__init__(provider, message, code=code, retryable=False)
