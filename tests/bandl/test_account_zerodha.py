"""Zerodha account mapping tests."""

from __future__ import annotations

from bandl.config import BandlConfig, ProviderSettings
from bandl.core.account_filters import AccountFilters
from bandl.providers.equity.zerodha import ZerodhaProvider


def test_zerodha_capabilities() -> None:
    prov = ZerodhaProvider(BandlConfig())
    caps = prov.account_capabilities()
    assert caps.fills.supported is True
    assert caps.orders.notes
    assert "session" in caps.orders.notes[0].lower() or "day" in caps.orders.notes[0].lower()


def test_zerodha_get_orders_day(monkeypatch) -> None:
    prov = ZerodhaProvider(
        BandlConfig(
            providers={
                "zerodha": ProviderSettings(api_key="k", access_token="t"),
            },
        ),
    )

    def fake_get(url: str, *, provider: str, params=None, headers=None):
        if url.endswith("/orders"):
            return [
                {
                    "order_id": "1",
                    "exchange": "NSE",
                    "tradingsymbol": "RELIANCE",
                    "transaction_type": "BUY",
                    "order_type": "MARKET",
                    "status": "COMPLETE",
                    "quantity": 10,
                    "filled_quantity": 10,
                    "order_timestamp": "2024-01-15 10:00:00+05:30",
                    "product": "CNC",
                },
            ]
        return []

    prov._http.get_json = fake_get  # type: ignore[method-assign]
    orders = prov.get_orders(AccountFilters())
    assert len(orders) == 1
    assert orders[0].symbol == "NSE:RELIANCE"
    assert orders[0].status == "complete"


def test_zerodha_ledger_unsupported_when_disabled(monkeypatch) -> None:
    prov = ZerodhaProvider(
        BandlConfig(providers={"zerodha": ProviderSettings(api_key="k", access_token="t")}),
    )
    caps = prov.account_capabilities()
    assert caps.ledger.supported
