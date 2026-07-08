"""Live order write/read facet on the Bandl client."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from bandl.core.capabilities import TradeCapabilities
from bandl.core.dataframe import models_to_dataframe
from bandl.core.provider import TradingProvider
from bandl.exceptions import ConfigurationError, UnsupportedCapabilityError
from bandl.models.account import AccountFill
from bandl.models.trading import Order, OrderRequest


def _require(provider_id: str, capability: str, supported: bool) -> None:
    if not supported:
        raise UnsupportedCapabilityError(provider_id, capability)


@dataclass
class TradeFacet:
    client: Any

    def _provider(self, source: str) -> TradingProvider:
        prov = self.client._get_provider(source)
        if not isinstance(prov, TradingProvider):
            raise ConfigurationError(f"Provider '{source}' does not support trading")
        return prov

    def capabilities(self, source: str) -> TradeCapabilities:
        return self._provider(source).trade_capabilities()

    def supports(self, source: str, capability: str) -> bool:
        return self.capabilities(source).supports(capability)

    def place_order(self, order: OrderRequest, *, source: str) -> Order:
        prov = self._provider(source)
        caps = prov.trade_capabilities()
        _require(source, "place", caps.place.supported)
        return prov.place_order(order)

    def modify_order(
        self,
        order_id: str,
        *,
        source: str,
        price: Any = None,
        trigger_price: Any = None,
        quantity: Any = None,
        validity: Any = None,
    ) -> Order:
        prov = self._provider(source)
        caps = prov.trade_capabilities()
        _require(source, "modify", caps.modify.supported)
        return prov.modify_order(
            order_id,
            price=price,
            trigger_price=trigger_price,
            quantity=quantity,
            validity=validity,
        )

    def cancel_order(self, order_id: str, *, source: str) -> Order:
        prov = self._provider(source)
        caps = prov.trade_capabilities()
        _require(source, "cancel", caps.cancel.supported)
        return prov.cancel_order(order_id)

    def get_open_orders(self, *, source: str, symbol: str | None = None) -> list[Order]:
        prov = self._provider(source)
        caps = prov.trade_capabilities()
        _require(source, "get_open_orders", caps.get_open_orders.supported)
        return prov.get_open_orders(symbol=symbol)

    def get_open_orders_dataframe(self, *args: Any, **kwargs: Any) -> pd.DataFrame:
        return models_to_dataframe(self.get_open_orders(*args, **kwargs))

    def get_order(self, order_id: str, *, source: str) -> Order:
        prov = self._provider(source)
        caps = prov.trade_capabilities()
        _require(source, "get_order", caps.get_order.supported)
        return prov.get_order(order_id)

    def get_trades(self, *, source: str, symbol: str | None = None) -> list[AccountFill]:
        prov = self._provider(source)
        caps = prov.trade_capabilities()
        _require(source, "get_trades", caps.get_trades.supported)
        return prov.get_trades(symbol=symbol)

    def get_trades_dataframe(self, *args: Any, **kwargs: Any) -> pd.DataFrame:
        return models_to_dataframe(self.get_trades(*args, **kwargs))
