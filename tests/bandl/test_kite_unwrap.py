from __future__ import annotations

import pytest

from bandl.exceptions import ProviderError
from bandl.providers.equity.zerodha.common import kite_unwrap


def test_kite_unwrap_list() -> None:
    assert kite_unwrap({"status": "success", "data": [{"a": 1}]}) == [{"a": 1}]


def test_kite_unwrap_error() -> None:
    with pytest.raises(ProviderError, match="Kite API error"):
        kite_unwrap({"status": "error", "message": "bad token"})
