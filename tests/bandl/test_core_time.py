from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from bandl.core.time import (
    default_time_range,
    ensure_utc,
    parse_epoch_ms,
    to_epoch_ms,
    to_epoch_sec,
)
from bandl.exceptions import BandlError


def test_ensure_utc_naive() -> None:
    dt = datetime(2024, 1, 1, 12, 0, 0)
    out = ensure_utc(dt)
    assert out.tzinfo == timezone.utc
    assert out.hour == 12


def test_default_time_range_defaults() -> None:
    end = datetime(2024, 6, 1, tzinfo=timezone.utc)
    start, end_dt = default_time_range(None, end, default_days=7)
    assert (end_dt - start).days == 7
    assert end_dt == end


def test_default_time_range_invalid_raises() -> None:
    t = datetime(2024, 6, 1, tzinfo=timezone.utc)
    with pytest.raises(BandlError, match="start must be before end"):
        default_time_range(t, t - timedelta(days=1))


def test_parse_epoch_ms_seconds_and_millis() -> None:
    sec = int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp())
    ms = sec * 1000
    assert parse_epoch_ms(sec) == parse_epoch_ms(ms)


def test_to_epoch_helpers() -> None:
    dt = datetime(2024, 1, 1, tzinfo=timezone.utc)
    assert to_epoch_sec(dt) * 1000 == to_epoch_ms(dt)
