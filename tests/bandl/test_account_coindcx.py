"""CoinDCX account fill mapping tests."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from bandl.config import BandlConfig, ProviderSettings
from bandl.core.account_filters import AccountFilters
from bandl.providers.crypto.coindcx import CoinDCXProvider


def test_map_coindcx_fill() -> None:
    prov = CoinDCXProvider(
        BandlConfig(
            providers={
                "coindcx": ProviderSettings(api_key="k", api_secret="s"),
            },
        ),
    )
    row = {
        "id": 564389,
        "order_id": "ee060ab6-40ed-11e8-b4b9-3f2ce29cd280",
        "side": "buy",
        "fee_amount": "0.00001129",
        "quantity": 67.9,
        "price": 0.00008272,
        "symbol": "BTCINR",
        "timestamp": 1533700109811,
    }
    fill = prov._map_coindcx_fill(row)
    assert fill.fill_id == "564389"
    assert fill.side == "buy"
    assert fill.fee == Decimal("0.00001129")
    assert fill.dedup_key == "coindcx:fill:564389"
    assert fill.executed_at.tzinfo is not None


def test_coindcx_capabilities() -> None:
    prov = CoinDCXProvider(BandlConfig())
    caps = prov.account_capabilities()
    assert caps.fills.supported is True
    assert caps.pnl_computed.supported is True
    assert caps.pnl_broker.supported is True


def test_coindcx_get_fills_pagination(monkeypatch) -> None:
    prov = CoinDCXProvider(
        BandlConfig(providers={"coindcx": ProviderSettings(api_key="k", api_secret="s")}),
    )
    calls: list[dict] = []

    def fake_post(url: str, *, provider: str, body: dict | None = None, headers=None):
        calls.append(body or {})
        if len(calls) == 1:
            return [
                {
                    "id": 1,
                    "order_id": "o1",
                    "side": "buy",
                    "fee_amount": "0",
                    "quantity": 1,
                    "price": 100,
                    "symbol": "BTCINR",
                    "timestamp": 1533700109811,
                },
            ]
        return []

    prov._http.post_json = fake_post  # type: ignore[method-assign]
    start = datetime(2018, 8, 1, tzinfo=timezone.utc)
    end = datetime(2018, 8, 10, tzinfo=timezone.utc)
    fills = prov.get_fills(AccountFilters(start=start, end=end))
    assert len(fills) == 1
    assert len(calls) >= 1
