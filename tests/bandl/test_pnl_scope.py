"""Zerodha get_pnl day/net/holding scope tests (fixes silent double-counting)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from bandl.config import BandlConfig, ProviderSettings
from bandl.core.account_filters import AccountFilters
from bandl.exceptions import ProviderError
from bandl.providers.equity.zerodha import ZerodhaProvider

_HOLDINGS = [
    {"tradingsymbol": "INFY", "pnl": 500.0},
]

_POSITIONS = {
    "net": [
        {
            "tradingsymbol": "RELIANCE",
            "exchange": "NFO",
            "product": "NRML",
            "quantity": 10,
            "unrealised": -20.0,
            "realised": 100.0,
            "pnl": 80.0,
        },
    ],
    "day": [
        {
            # squared off intraday -> Kite costs this at a zero average price
            "tradingsymbol": "SBIN",
            "exchange": "NFO",
            "product": "MIS",
            "quantity": 0,
            "average_price": 0,
            "unrealised": 0.0,
            "realised": -40330.0,
            "pnl": -40330.0,
        },
        {
            # still open intraday, real average price -> not an artifact
            "tradingsymbol": "TCS",
            "exchange": "NFO",
            "product": "MIS",
            "quantity": 5,
            "average_price": 3500.0,
            "unrealised": 250.0,
            "realised": 0.0,
            "pnl": 250.0,
        },
    ],
}


def _provider() -> ZerodhaProvider:
    return ZerodhaProvider(
        BandlConfig(),
        ProviderSettings(api_key="k", access_token="t"),
    )


def _fake_get(url: str, *, provider: str, params=None, headers=None):
    if url.endswith("/portfolio/holdings"):
        return {"status": "success", "data": _HOLDINGS}
    if url.endswith("/portfolio/positions"):
        return {"status": "success", "data": _POSITIONS}
    if url.endswith("/orders"):
        return {"status": "success", "data": []}
    if url.endswith("/trades"):
        return {"status": "success", "data": []}
    return {"status": "success", "data": []}


def test_default_scope_excludes_day_book() -> None:
    prov = _provider()
    prov._http.get_json = _fake_get

    rows = prov.get_pnl(AccountFilters(), prefer="broker")
    assert rows  # net + holding present
    assert all(r.scope != "day" for r in rows)
    scopes = {r.scope for r in rows}
    assert scopes == {"net", "holding"}


def test_scope_day_isolates_day_book_and_flags_zero_avg() -> None:
    prov = _provider()
    prov._http.get_json = _fake_get

    rows = prov.get_pnl(AccountFilters(), prefer="broker", scope="day")
    assert len(rows) == 2
    assert all(r.scope == "day" for r in rows)

    sbin = next(r for r in rows if r.symbol_native == "SBIN")
    assert sbin.zero_avg_price_artifact is True
    assert sbin.provenance.confidence == "low"

    tcs = next(r for r in rows if r.symbol_native == "TCS")
    assert tcs.zero_avg_price_artifact is False


def test_scope_all_returns_every_book() -> None:
    prov = _provider()
    prov._http.get_json = _fake_get

    rows = prov.get_pnl(AccountFilters(), prefer="broker", scope="all")
    scopes = [r.scope for r in rows]
    assert scopes.count("net") == 1
    assert scopes.count("day") == 2
    assert scopes.count("holding") == 1


def test_scope_net_isolates_net_only() -> None:
    prov = _provider()
    prov._http.get_json = _fake_get

    rows = prov.get_pnl(AccountFilters(), prefer="broker", scope="net")
    assert len(rows) == 1
    assert rows[0].scope == "net"
    assert rows[0].symbol_native == "RELIANCE"


def test_invalid_scope_raises() -> None:
    prov = _provider()
    prov._http.get_json = _fake_get
    with pytest.raises(ProviderError):
        prov.get_pnl(AccountFilters(), prefer="broker", scope="bogus")


def _fake_get_with_one_order(url: str, *, provider: str, params=None, headers=None):
    if url.endswith("/portfolio/holdings"):
        return {"status": "success", "data": []}
    if url.endswith("/portfolio/positions"):
        return {"status": "success", "data": {"net": [], "day": []}}
    if url.endswith("/orders"):
        return {
            "status": "success",
            "data": [
                {
                    "order_id": "1",
                    "exchange": "NSE",
                    "tradingsymbol": "RELIANCE",
                    "transaction_type": "BUY",
                    "order_type": "MARKET",
                    "status": "COMPLETE",
                    "quantity": 1,
                    "filled_quantity": 1,
                    "order_timestamp": "2026-07-08 10:00:00+05:30",
                    "product": "CNC",
                },
            ],
        }
    if url.endswith("/trades"):
        return {"status": "success", "data": []}
    return {"status": "success", "data": []}


def test_ledger_failure_degrades_instead_of_crashing() -> None:
    prov = _provider()
    prov._http.get_json = _fake_get_with_one_order
    prov._http.post_json = MagicMock(
        side_effect=ProviderError("zerodha", "HTTP 500 for /charges/orders: boom"),
    )

    # Must not raise, even though /charges/orders 500s.
    rows = prov.get_pnl(AccountFilters(), prefer="computed")
    assert isinstance(rows, list)
    if rows:
        assert any("degraded" in w for w in rows[0].provenance.warnings)


def test_reconcile_true_does_not_crash_on_ledger_failure() -> None:
    prov = _provider()
    prov._http.get_json = _fake_get_with_one_order
    prov._http.post_json = MagicMock(
        side_effect=ProviderError("zerodha", "HTTP 500 for /charges/orders: boom"),
    )

    rows = prov.get_pnl(AccountFilters(), prefer="auto", reconcile=True)
    assert isinstance(rows, list)
