"""Thin HTTP layer with retries for provider adapters."""

from __future__ import annotations

import json
import random
import re
import time
from collections.abc import Mapping
from typing import Any, Literal
from urllib.parse import urlparse, urlunparse

import httpx

from bandl.config import BandlConfig
from bandl.exceptions import (
    AuthenticationError,
    GeoRestrictionError,
    InsufficientFundsError,
    InvalidOrderError,
    OrderRejectedError,
    ProviderError,
    RateLimitError,
    UncertainOutcomeError,
)


def _safe_url_for_errors(url: Any) -> str:
    """Strip query string and fragment so error messages do not leak sensitive params."""
    try:
        p = urlparse(str(url))
        return urlunparse((p.scheme, p.netloc, p.path, "", "", ""))
    except Exception:
        return "<url>"


def _is_sensitive_key(key: Any) -> bool:
    """Check if a dictionary key represents sensitive auth/secret data under normalized spelling."""
    k_norm = re.sub(r"[-_]", "", str(key).lower())
    sensitive_patterns = (
        "authorization",
        "apikey",
        "accesstoken",
        "token",
        "secret",
        "password",
        "auth",
    )
    return any(p in k_norm for p in sensitive_patterns)


def _redact_value(val: Any) -> Any:
    """Recursively redact sensitive keys and values from mappings, sequences, sets, and strings."""
    if isinstance(val, Mapping):
        return {
            k: ("[REDACTED]" if _is_sensitive_key(k) else _redact_value(v)) for k, v in val.items()
        }
    if isinstance(val, (list, tuple)):
        redacted_seq = [_redact_value(item) for item in val]
        return type(val)(redacted_seq) if isinstance(val, tuple) else redacted_seq
    if isinstance(val, set):
        return {_redact_value(item) for item in val}
    if isinstance(val, str):
        return _redact_text(val)
    return val


def _redact_dict(d: Mapping[str, Any] | None) -> dict[str, Any]:
    """Redact sensitive auth tokens, passwords, and secrets from context dictionaries
    recursively."""
    if not d:
        return {}
    res = _redact_value(d)
    return dict(res) if isinstance(res, dict) else {}


def _redact_text(text: str) -> str:
    """Redact sensitive keys/values and url query strings from arbitrary text."""
    if not text:
        return text
    # Try parsing as JSON first
    if text.strip().startswith(("{", "[")):
        try:
            data = json.loads(text)
            if isinstance(data, (dict, list)):
                redacted_data = _redact_value(data)
                return json.dumps(redacted_data)
        except Exception:
            pass

    # Strip query parameters from any URLs found in text
    def _sanitize_url_match(m: re.Match[str]) -> str:
        return _safe_url_for_errors(m.group(0))

    text = re.sub(r"https?://[^\s\"'>]+", _sanitize_url_match, text)

    # Redact Authorization header with optional scheme (token, Bearer, Basic) and credentials
    auth_header_regex = re.compile(
        r"""(?i)(?P<prefix>["']?authorization["']?\s*[:=]\s*["']?(?:bearer\s+|token\s+|basic\s+)?)(?P<cred>[^\s,;}{"'\\]+)"""
    )
    text = auth_header_regex.sub(r"\g<prefix>[REDACTED]", text)

    # Redact sensitive key-value pairs (key=value, "key": "value", key: value)
    sensitive_regex = re.compile(
        r"""(?i)(?P<key>["']?(?:api[_-]?key|access[_-]?token|token|secret|password)["']?\s*[:=]\s*)(?P<val>["']?[^\s,;}{"'\\]+["']?)"""
    )
    text = sensitive_regex.sub(r"\g<key>[REDACTED]", text)

    # Redact Bearer tokens
    text = re.sub(r"""(?i)\bbearer\s+[^\s,;}{'"]+""", "Bearer [REDACTED]", text)
    return text


def _safe_diagnostic(payload: Any, max_len: int = 500) -> str:
    """Sanitize and bound diagnostics for safe exception formatting."""
    if payload is None:
        return "None"
    redacted = _redact_value(payload)
    text = repr(redacted)
    text = _redact_text(text)
    if len(text) > max_len:
        text = f"{text[:max_len]}..."
    return text


def _safe_exception_str(exc: Exception | None) -> str:
    """Format an exception safely without leaking query strings from URLs or credentials."""
    if exc is None:
        return ""
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code if exc.response is not None else "?"
        url = _safe_url_for_errors(exc.request.url) if exc.request is not None else "<url>"
        return f"HTTPStatusError: {code} for {url}"
    if isinstance(exc, httpx.RequestError):
        err_type = type(exc).__name__
        url = _safe_url_for_errors(exc.request.url) if exc.request is not None else "<url>"
        return f"{err_type} for {url}"
    return _redact_text(str(exc))


def _sleep_backoff(attempt: int) -> None:
    """Exponential backoff with jitter before the next HTTP retry."""
    delay = min(8.0, 0.5 * (2**attempt)) + random.uniform(0, 0.15)
    time.sleep(delay)


def _parse_retry_after(headers: Mapping[str, str] | None) -> float | None:
    if not headers:
        return None
    ra = headers.get("Retry-After") or headers.get("retry-after")
    if not ra:
        return None
    try:
        return float(ra)
    except (ValueError, TypeError):
        return None


def _provider_http_error(provider: str, exc: httpx.HTTPStatusError) -> ProviderError:
    """Turn an httpx HTTP error into a safe Bandl error; sanitize and bound body."""
    status_code = exc.response.status_code
    code = str(status_code)
    safe_url = _safe_url_for_errors(exc.request.url)

    raw_detail = exc.response.text.strip()
    detail = _redact_text(raw_detail)
    if len(detail) > 1000:
        detail = f"{detail[:1000]}..."
    msg = f"HTTP {code} for {safe_url}"
    if detail:
        msg = f"{msg}: {detail}"

    retry_after = _parse_retry_after(exc.response.headers)
    if status_code == 429:
        return RateLimitError(provider, msg, code=code, retryable=True, retry_after=retry_after)
    if status_code in (401, 403):
        return AuthenticationError(provider, msg, code=code)
    if status_code == 451:
        hint = (
            " This usually means Binance blocks your region or IP "
            "(common on US cloud hosts and Colab). "
            "Try source='coindcx' for crypto, or run from a permitted network."
        )
        return GeoRestrictionError(provider, msg + hint, code=code)

    # Inspect structured JSON payloads for documented broker rejections
    try:
        body_json = exc.response.json()
    except Exception:
        body_json = None

    if isinstance(body_json, dict):
        prov_lower = provider.lower()
        if prov_lower in ("zerodha", "kite"):
            # Zerodha Kite Connect error envelope
            kite_error_type = body_json.get("error_type")
            raw_kite_msg = body_json.get("message")
            kite_msg = _redact_text(str(raw_kite_msg)) if raw_kite_msg else msg
            if kite_error_type == "TokenException":
                return AuthenticationError(provider, f"[{provider}] {kite_msg}", code=code)
            if kite_error_type == "OrderException":
                k_lower = kite_msg.lower()
                if "margin" in k_lower or "insufficient" in k_lower or "funds" in k_lower:
                    return InsufficientFundsError(provider, kite_msg, code=code)
                return OrderRejectedError(provider, kite_msg, raw_status="REJECTED", code=code)
            if kite_error_type == "InputException":
                return InvalidOrderError(provider, kite_msg, code=code)

        elif prov_lower == "dhan":
            # Dhan error envelope
            dhan_code = str(body_json.get("errorCode") or "")
            dhan_type = str(body_json.get("errorType") or "")
            raw_dhan_msg = (
                body_json.get("remarks")
                or body_json.get("errorMessage")
                or body_json.get("message")
            )
            dhan_msg = _redact_text(str(raw_dhan_msg)) if raw_dhan_msg else msg
            if (
                dhan_code in ("DH-901", "DH-902", "DH-903")
                or dhan_type in ("Invalid_Authentication", "AUTHENTICATION_ERROR")
                or re.search(r"\bIP\b", dhan_msg)
                or "WHITELIST" in dhan_msg.upper()
            ):
                return AuthenticationError(provider, f"[{provider}] {dhan_msg}", code=code)
            if dhan_code == "DH-905" or dhan_type in ("Input_Exception", "INPUT_ERROR"):
                return InvalidOrderError(provider, dhan_msg, code=code)
            if (
                "Order" in dhan_type
                or dhan_code.startswith("DH-")
                or dhan_type in ("BUSINESS_ERROR", "TRANSACTION_ERROR")
            ):
                d_lower = dhan_msg.lower()
                if "margin" in d_lower or "insufficient" in d_lower or "funds" in d_lower:
                    return InsufficientFundsError(provider, dhan_msg, code=code)
                return OrderRejectedError(provider, dhan_msg, raw_status="REJECTED", code=code)

    return ProviderError(provider, msg, code=code)


class HttpClient:
    """Small synchronous httpx wrapper."""

    def __init__(self, config: BandlConfig, transport: httpx.BaseTransport | None = None) -> None:
        self._config = config
        self._client = httpx.Client(
            timeout=config.timeout_seconds,
            headers={"User-Agent": config.user_agent},
            transport=transport,
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
                    ra = _parse_retry_after(e.response.headers)
                    raise RateLimitError(
                        provider, "Rate limited", code="429", retryable=True, retry_after=ra
                    ) from e
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
        raise ProviderError(
            provider, f"HTTP failure after retries: {_safe_exception_str(last_exc)}"
        ) from last_exc

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
                    ra = _parse_retry_after(e.response.headers)
                    raise RateLimitError(
                        provider, "Rate limited", code="429", retryable=True, retry_after=ra
                    ) from e
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
        raise ProviderError(
            provider, f"HTTP failure after retries: {_safe_exception_str(last_exc)}"
        ) from last_exc

    def post_json(
        self,
        url: str,
        *,
        provider: str,
        body: Mapping[str, Any] | None = None,
        data: Mapping[str, Any] | None = None,
        encoding: Literal["json", "form"] = "json",
        headers: Mapping[str, str] | None = None,
        retryable: bool = True,
        context: dict[str, Any] | None = None,
    ) -> Any:
        ctx = _redact_dict(context or {})
        payload = data if data is not None else body
        if not retryable:
            try:
                if encoding == "form":
                    resp = self._client.post(url, data=payload or {}, headers=headers)
                else:
                    resp = self._client.post(url, json=payload or {}, headers=headers)
                resp.raise_for_status()
                try:
                    return resp.json()
                except Exception as json_err:
                    raise UncertainOutcomeError(
                        provider,
                        f"Server returned invalid JSON after mutation dispatch: {json_err}",
                        operation=ctx.get("operation", "place"),
                        order_id=ctx.get("order_id"),
                        client_order_id=ctx.get("client_order_id"),
                        request_context=ctx,
                    ) from json_err
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    ra = _parse_retry_after(e.response.headers)
                    raise RateLimitError(
                        provider, "Rate limited", code="429", retryable=True, retry_after=ra
                    ) from e
                if 400 <= e.response.status_code < 500:
                    raise _provider_http_error(provider, e) from e
                code = str(e.response.status_code)
                err_str = _safe_exception_str(e)
                raise UncertainOutcomeError(
                    provider,
                    f"Server error {code} during mutation (outcome uncertain): {err_str}",
                    operation=ctx.get("operation", "place"),
                    order_id=ctx.get("order_id"),
                    client_order_id=ctx.get("client_order_id"),
                    request_context=ctx,
                    code=code,
                ) from e
            except httpx.RequestError as e:
                err_str = _safe_exception_str(e)
                raise UncertainOutcomeError(
                    provider,
                    f"Network failure during mutation (outcome uncertain): {err_str}",
                    operation=ctx.get("operation", "place"),
                    order_id=ctx.get("order_id"),
                    client_order_id=ctx.get("client_order_id"),
                    request_context=ctx,
                ) from e

        last_exc: Exception | None = None
        for attempt in range(self._config.max_http_retries + 1):
            try:
                if encoding == "form":
                    resp = self._client.post(url, data=payload or {}, headers=headers)
                else:
                    resp = self._client.post(url, json=payload or {}, headers=headers)
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    ra = _parse_retry_after(e.response.headers)
                    raise RateLimitError(
                        provider, "Rate limited", code="429", retryable=True, retry_after=ra
                    ) from e
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
        raise ProviderError(
            provider, f"HTTP failure after retries: {_safe_exception_str(last_exc)}"
        ) from last_exc

    def post_mutation(
        self,
        url: str,
        *,
        provider: str,
        body: Mapping[str, Any] | None = None,
        data: Mapping[str, Any] | None = None,
        encoding: Literal["json", "form"] = "json",
        headers: Mapping[str, str] | None = None,
        context: dict[str, Any] | None = None,
    ) -> Any:
        """POST with NO automatic retries — mutations must never be replayed blindly."""
        return self.post_json(
            url,
            provider=provider,
            body=body,
            data=data,
            encoding=encoding,
            headers=headers,
            retryable=False,
            context=context,
        )

    def post_form_mutation(
        self,
        url: str,
        *,
        provider: str,
        data: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        context: dict[str, Any] | None = None,
    ) -> Any:
        """POST form-encoded parameters with NO automatic retries."""
        return self.post_mutation(
            url,
            provider=provider,
            data=data,
            encoding="form",
            headers=headers,
            context=context,
        )

    def put_json(
        self,
        url: str,
        *,
        provider: str,
        body: Mapping[str, Any] | None = None,
        data: Mapping[str, Any] | None = None,
        encoding: Literal["json", "form"] = "json",
        headers: Mapping[str, str] | None = None,
        context: dict[str, Any] | None = None,
    ) -> Any:
        """PUT with no automatic retry — order modify must not be replayed blindly."""
        ctx = _redact_dict(context or {})
        payload = data if data is not None else body
        try:
            if encoding == "form":
                resp = self._client.put(url, data=payload or {}, headers=headers)
            else:
                resp = self._client.put(url, json=payload or {}, headers=headers)
            resp.raise_for_status()
            try:
                return resp.json()
            except Exception as json_err:
                raise UncertainOutcomeError(
                    provider,
                    f"Server returned invalid JSON after mutation dispatch: {json_err}",
                    operation=ctx.get("operation", "modify"),
                    order_id=ctx.get("order_id"),
                    client_order_id=ctx.get("client_order_id"),
                    request_context=ctx,
                ) from json_err
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                ra = _parse_retry_after(e.response.headers)
                raise RateLimitError(
                    provider, "Rate limited", code="429", retryable=True, retry_after=ra
                ) from e
            if 400 <= e.response.status_code < 500:
                raise _provider_http_error(provider, e) from e
            code = str(e.response.status_code)
            err_str = _safe_exception_str(e)
            raise UncertainOutcomeError(
                provider,
                f"Server error {code} during modify mutation (outcome uncertain): {err_str}",
                operation=ctx.get("operation", "modify"),
                order_id=ctx.get("order_id"),
                client_order_id=ctx.get("client_order_id"),
                request_context=ctx,
                code=code,
            ) from e
        except httpx.RequestError as e:
            err_str = _safe_exception_str(e)
            raise UncertainOutcomeError(
                provider,
                f"Network failure during modify mutation (outcome uncertain): {err_str}",
                operation=ctx.get("operation", "modify"),
                order_id=ctx.get("order_id"),
                client_order_id=ctx.get("client_order_id"),
                request_context=ctx,
            ) from e

    def put_mutation(
        self,
        url: str,
        *,
        provider: str,
        body: Mapping[str, Any] | None = None,
        data: Mapping[str, Any] | None = None,
        encoding: Literal["json", "form"] = "json",
        headers: Mapping[str, str] | None = None,
        context: dict[str, Any] | None = None,
    ) -> Any:
        """PUT with NO automatic retries — order modify must never be replayed blindly."""
        return self.put_json(
            url,
            provider=provider,
            body=body,
            data=data,
            encoding=encoding,
            headers=headers,
            context=context,
        )

    def put_form_mutation(
        self,
        url: str,
        *,
        provider: str,
        data: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        context: dict[str, Any] | None = None,
    ) -> Any:
        """PUT form-encoded parameters with NO automatic retries."""
        return self.put_mutation(
            url,
            provider=provider,
            data=data,
            encoding="form",
            headers=headers,
            context=context,
        )

    def delete_json(
        self,
        url: str,
        *,
        provider: str,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        context: dict[str, Any] | None = None,
    ) -> Any:
        """DELETE with no automatic retry — order cancel must not be replayed blindly."""
        ctx = _redact_dict(context or {})
        try:
            resp = self._client.delete(url, params=params, headers=headers)
            resp.raise_for_status()
            try:
                return resp.json()
            except Exception as json_err:
                raise UncertainOutcomeError(
                    provider,
                    f"Server returned invalid JSON after mutation dispatch: {json_err}",
                    operation=ctx.get("operation", "cancel"),
                    order_id=ctx.get("order_id"),
                    client_order_id=ctx.get("client_order_id"),
                    request_context=ctx,
                ) from json_err
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                ra = _parse_retry_after(e.response.headers)
                raise RateLimitError(
                    provider, "Rate limited", code="429", retryable=True, retry_after=ra
                ) from e
            if 400 <= e.response.status_code < 500:
                raise _provider_http_error(provider, e) from e
            code = str(e.response.status_code)
            err_str = _safe_exception_str(e)
            raise UncertainOutcomeError(
                provider,
                f"Server error {code} during cancel mutation (outcome uncertain): {err_str}",
                operation=ctx.get("operation", "cancel"),
                order_id=ctx.get("order_id"),
                client_order_id=ctx.get("client_order_id"),
                request_context=ctx,
                code=code,
            ) from e
        except httpx.RequestError as e:
            err_str = _safe_exception_str(e)
            raise UncertainOutcomeError(
                provider,
                f"Network failure during cancel mutation (outcome uncertain): {err_str}",
                operation=ctx.get("operation", "cancel"),
                order_id=ctx.get("order_id"),
                client_order_id=ctx.get("client_order_id"),
                request_context=ctx,
            ) from e

    def delete_mutation(
        self,
        url: str,
        *,
        provider: str,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        context: dict[str, Any] | None = None,
    ) -> Any:
        """DELETE with NO automatic retries — order cancel must never be replayed blindly."""
        return self.delete_json(
            url,
            provider=provider,
            params=params,
            headers=headers,
            context=context,
        )
