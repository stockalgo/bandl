"""HTTP client error mapping."""

from __future__ import annotations

from unittest.mock import MagicMock

import httpx
import pytest

from bandl.config import BandlConfig
from bandl.core.http import HttpClient
from bandl.exceptions import GeoRestrictionError


def test_binance_451_raises_geo_restriction_error() -> None:
    request = httpx.Request("GET", "https://api.binance.com/api/v3/klines")
    response = httpx.Response(
        451,
        request=request,
        json={
            "code": 0,
            "msg": "Service unavailable from a restricted location",
        },
    )
    client = HttpClient(BandlConfig())
    client._client.get = MagicMock(return_value=response)  # type: ignore[method-assign]

    with pytest.raises(GeoRestrictionError) as exc_info:
        client.get_json("https://api.binance.com/api/v3/klines", provider="binance")

    assert exc_info.value.code == "451"
    assert "coindcx" in str(exc_info.value).lower()
