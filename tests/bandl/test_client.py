"""Bandl client behavior."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from bandl import Bandl, ProviderSettings
from bandl.exceptions import ConfigurationError
from bandl.models.market.types import Interval


def test_unknown_provider_raises_configuration_error() -> None:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=1)
    with pytest.raises(ConfigurationError, match="not-a-provider"):
        Bandl().get_ohlcv(
            "BTC/USDT",
            Interval.D1,
            start,
            end,
            source="not-a-provider",
        )


def test_provider_settings_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        ProviderSettings(api_key="k", not_a_real_field="x")


def test_provider_settings_secrets_not_in_repr() -> None:
    s = ProviderSettings(api_key="secret-key", api_secret="secret-s", access_token="tok")
    r = repr(s)
    assert "secret-key" not in r
    assert "secret-s" not in r
    assert "tok" not in r
