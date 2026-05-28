"""Thin HTTP layer with retries for provider adapters."""

from __future__ import annotations

import random
import time
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse, urlunparse

import httpx

from bandl.config import BandlConfig
from bandl.exceptions import AuthenticationError, GeoRestrictionError, ProviderError


def _safe_url_for_errors(url: Any) -> str:
    """Strip query string and fragment so error messages do not leak sensitive params."""
    try:
        p = urlparse(str(url))
        return urlunparse((p.scheme, p.netloc, p.path, "", "", ""))
    except Exception:
        return "<url>"


def _sleep_backoff(attempt: int) -> None:
    """Exponential backoff with jitter before the next HTTP retry."""
    delay = min(8.0, 0.5 * (2**attempt)) + random.uniform(0, 0.15)
    time.sleep(delay)


def _provider_http_error(provider: str, exc: httpx.HTTPStatusError) -> ProviderError:
    """Turn an httpx HTTP error into a Bandl error; include response body when present."""
    code = str(exc.response.status_code)
    detail = exc.response.text.strip()
    if len(detail) > 1500:
        detail = f"{detail[:1500]}..."
    safe_url = _safe_url_for_errors(exc.request.url)
    msg = f"HTTP {code} for {safe_url}"
    if detail:
        msg = f"{msg}: {detail}"
    if exc.response.status_code in (401, 403):
        return AuthenticationError(provider, msg, code=code)
    if exc.response.status_code == 451:
        hint = (
            " This usually means Binance blocks your region or IP "
            "(common on US cloud hosts and Colab). "
            "Try source='coindcx' for crypto, or run from a permitted network."
        )
        return GeoRestrictionError(provider, msg + hint, code=code)
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
                if attempt < self._config.max_http_retries:
                    _sleep_backoff(attempt)
                else:
                    break
            except httpx.RequestError as e:
                last_exc = e
                if attempt < self._config.max_http_retries:
                    _sleep_backoff(attempt)
                else:
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
                if attempt < self._config.max_http_retries:
                    _sleep_backoff(attempt)
                else:
                    break
            except httpx.RequestError as e:
                last_exc = e
                if attempt < self._config.max_http_retries:
                    _sleep_backoff(attempt)
                else:
                    break
        if isinstance(last_exc, httpx.HTTPStatusError):
            raise _provider_http_error(provider, last_exc) from last_exc
        raise ProviderError(provider, f"HTTP failure after retries: {last_exc}") from last_exc

    def post_json(
        self,
        url: str,
        *,
        provider: str,
        body: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        last_exc: Exception | None = None
        for attempt in range(self._config.max_http_retries + 1):
            try:
                resp = self._client.post(url, json=body or {}, headers=headers)
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    raise ProviderError(provider, "Rate limited", code="429", retryable=True) from e
                if 400 <= e.response.status_code < 500:
                    raise _provider_http_error(provider, e) from e
                last_exc = e
                if attempt < self._config.max_http_retries:
                    _sleep_backoff(attempt)
                else:
                    break
            except httpx.RequestError as e:
                last_exc = e
                if attempt < self._config.max_http_retries:
                    _sleep_backoff(attempt)
                else:
                    break
        if isinstance(last_exc, httpx.HTTPStatusError):
            raise _provider_http_error(provider, last_exc) from last_exc
        raise ProviderError(provider, f"HTTP failure after retries: {last_exc}") from last_exc
