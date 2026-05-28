from __future__ import annotations

import pytest

from bandl.core.intervals import map_interval
from bandl.exceptions import ProviderError
from bandl.models.market.types import Interval


def test_map_interval_enum() -> None:
    mapping = {Interval.D1: "1d", Interval.H1: "1h"}
    assert map_interval(Interval.D1, mapping, "test") == "1d"


def test_map_interval_string_with_normalize() -> None:
    mapping = {Interval.D1: "1d"}
    assert map_interval("1D", mapping, "test", normalize=str.lower) == "1d"


def test_map_interval_unsupported() -> None:
    with pytest.raises(ProviderError, match="Unsupported interval"):
        map_interval(Interval.M3, {Interval.D1: "1d"}, "test")
