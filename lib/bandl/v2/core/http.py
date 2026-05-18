"""Thin HTTP layer with retries for provider adapters."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx

from bandl.v2.config import BandlConfig
from bandl.v2.exceptions import AuthenticationError, ProviderError


def _provider_http_error(provider: str, exc: httpx.HTTPStatusError) -> ProviderError:
    """Turn an httpx HTTP error into a Bandl error; include response body when present."""
    code = str(exc.response.status_code)
    detail = exc.response.text.strip()
    if len(detail) > 1500:
        detail = f"{detail[:1500]}..."
    msg = f"HTTP {code} for {exc.request.url}"
    if detail:
        msg = f"{msg}: {detail}"
    if exc.response.status_code in (401, 403):
        return AuthenticationError(provider, msg, code=code)
    return ProviderError(provider, msg, code=code)


class HttpClient:
    """Small synchronous httpx wrapper."""

    def __init__(self, config: BandlConfig) -> None:
        self._config = config
        self._client = httpx.Client(
            timeout=config.timeout_seconds,
            headers={"User-Agent": config.user_agent},
        )

    def close(self) -> None:
        self._client.close()

    def get_json(
        self,
        url: str,
        *,
        provider: str,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        last_exc: Exception | None = None
        for attempt in range(self._config.max_http_retries + 1):
            try:
                resp = self._client.get(url, params=params, headers=headers)
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    raise ProviderError(provider, "Rate limited", code="429", retryable=True) from e
                # Client errors: no point retrying; surface body (e.g. Kite JSON message).
                if 400 <= e.response.status_code < 500:
                    raise _provider_http_error(provider, e) from e
                last_exc = e
                if attempt >= self._config.max_http_retries:
                    break
            except httpx.RequestError as e:
                last_exc = e
                if attempt >= self._config.max_http_retries:
                    break
        if isinstance(last_exc, httpx.HTTPStatusError):
            raise _provider_http_error(provider, last_exc) from last_exc
        raise ProviderError(provider, f"HTTP failure after retries: {last_exc}") from last_exc

    def get_text(
        self,
        url: str,
        *,
        provider: str,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> str:
        last_exc: Exception | None = None
        for attempt in range(self._config.max_http_retries + 1):
            try:
                resp = self._client.get(url, params=params, headers=headers)
                resp.raise_for_status()
                return resp.text
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    raise ProviderError(provider, "Rate limited", code="429", retryable=True) from e
                if 400 <= e.response.status_code < 500:
                    raise _provider_http_error(provider, e) from e
                last_exc = e
                if attempt >= self._config.max_http_retries:
                    break
            except httpx.RequestError as e:
                last_exc = e
                if attempt >= self._config.max_http_retries:
                    break
        if isinstance(last_exc, httpx.HTTPStatusError):
            raise _provider_http_error(provider, last_exc) from last_exc
        raise ProviderError(provider, f"HTTP failure after retries: {last_exc}") from last_exc
