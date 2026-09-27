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
from bandl.models.trading import Order, OrderAcknowledgement, OrderRequest
from bandl.trade.validation import resolve_account_binding, verify_account_binding


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

    def place_order(
        self, order: OrderRequest, *, source: str, account_id: str | None = None
    ) -> Order:
        prov = self._provider(source)
        caps = prov.trade_capabilities()
        _require(source, "place", caps.place.supported)
        fn = getattr(prov, "place_order", None)
        if not callable(fn):
            raise UnsupportedCapabilityError(source, "place")
        effective_account_id = resolve_account_binding(
            prov, account_id=account_id, order_account_id=order.account_id
        )
        return fn(order, account_id=effective_account_id)

    def place_order_ack(
        self, order: OrderRequest, *, source: str, account_id: str | None = None
    ) -> OrderAcknowledgement:
        prov = self._provider(source)
        caps = prov.trade_capabilities()
        _require(source, "place", caps.place.supported)
        effective_account_id = resolve_account_binding(
            prov, account_id=account_id, order_account_id=order.account_id
        )
        ack_fn = getattr(prov, "place_order_ack", None)
        if not callable(ack_fn):
            raise UnsupportedCapabilityError(source, "place_order_ack")
        return ack_fn(order, account_id=effective_account_id)

    def modify_order(
        self,
        order_id: str,
        *,
        source: str,
        account_id: str | None = None,
        price: Any = None,
        trigger_price: Any = None,
        quantity: Any = None,
        validity: Any = None,
    ) -> Order:
        prov = self._provider(source)
        caps = prov.trade_capabilities()
        _require(source, "modify", caps.modify.supported)
        fn = getattr(prov, "modify_order", None)
        if not callable(fn):
            raise UnsupportedCapabilityError(source, "modify")
        verify_account_binding(prov, account_id)
        return fn(
            order_id,
            account_id=account_id,
            price=price,
            trigger_price=trigger_price,
            quantity=quantity,
            validity=validity,
        )

    def modify_order_ack(
        self,
        order_id: str,
        *,
        source: str,
        account_id: str | None = None,
        price: Any = None,
        trigger_price: Any = None,
        quantity: Any = None,
        validity: Any = None,
    ) -> OrderAcknowledgement:
        prov = self._provider(source)
        caps = prov.trade_capabilities()
        _require(source, "modify", caps.modify.supported)
        verify_account_binding(prov, account_id)
        ack_fn = getattr(prov, "modify_order_ack", None)
        if not callable(ack_fn):
            raise UnsupportedCapabilityError(source, "modify_order_ack")
        return ack_fn(
            order_id,
            account_id=account_id,
            price=price,
            trigger_price=trigger_price,
            quantity=quantity,
            validity=validity,
        )

    def cancel_order(self, order_id: str, *, source: str, account_id: str | None = None) -> Order:
        prov = self._provider(source)
        caps = prov.trade_capabilities()
        _require(source, "cancel", caps.cancel.supported)
        fn = getattr(prov, "cancel_order", None)
        if not callable(fn):
            raise UnsupportedCapabilityError(source, "cancel")
        verify_account_binding(prov, account_id)
        return fn(order_id, account_id=account_id)

    def cancel_order_ack(
        self, order_id: str, *, source: str, account_id: str | None = None
    ) -> OrderAcknowledgement:
        prov = self._provider(source)
        caps = prov.trade_capabilities()
        _require(source, "cancel", caps.cancel.supported)
        verify_account_binding(prov, account_id)
        ack_fn = getattr(prov, "cancel_order_ack", None)
        if not callable(ack_fn):
            raise UnsupportedCapabilityError(source, "cancel_order_ack")
        return ack_fn(order_id, account_id=account_id)

    def get_open_orders(
        self, *, source: str, symbol: str | None = None, account_id: str | None = None
    ) -> list[Order]:
        prov = self._provider(source)
        caps = prov.trade_capabilities()
        _require(source, "get_open_orders", caps.get_open_orders.supported)
        fn = getattr(prov, "get_open_orders", None)
        if not callable(fn):
            raise UnsupportedCapabilityError(source, "get_open_orders")
        verify_account_binding(prov, account_id)
        return fn(symbol=symbol, account_id=account_id)

    def get_open_orders_dataframe(self, *args: Any, **kwargs: Any) -> pd.DataFrame:
        return models_to_dataframe(self.get_open_orders(*args, **kwargs))

    def get_orders(
        self, *, source: str, symbol: str | None = None, account_id: str | None = None
    ) -> list[Order]:
        prov = self._provider(source)
        caps = prov.trade_capabilities()
        _require(source, "get_orders", caps.get_orders.supported)
        verify_account_binding(prov, account_id)
        t_fn = getattr(prov, "get_trading_orders", None)
        if callable(t_fn):
            return t_fn(symbol=symbol, account_id=account_id)
        o_fn = getattr(prov, "get_orders", None)
        if callable(o_fn):
            return o_fn(symbol=symbol, account_id=account_id)
        raise UnsupportedCapabilityError(source, "get_orders")

    def get_orders_dataframe(self, *args: Any, **kwargs: Any) -> pd.DataFrame:
        return models_to_dataframe(self.get_orders(*args, **kwargs))

    def get_order(self, order_id: str, *, source: str, account_id: str | None = None) -> Order:
        prov = self._provider(source)
        caps = prov.trade_capabilities()
        _require(source, "get_order", caps.get_order.supported)
        fn = getattr(prov, "get_order", None)
        if not callable(fn):
            raise UnsupportedCapabilityError(source, "get_order")
        verify_account_binding(prov, account_id)
        return fn(order_id, account_id=account_id)

    def get_order_history(
        self, order_id: str, *, source: str, account_id: str | None = None
    ) -> list[Order]:
        prov = self._provider(source)
        caps = prov.trade_capabilities()
        _require(source, "order_history", caps.get_order_history.supported)
        fn = getattr(prov, "get_order_history", None)
        if not callable(fn):
            raise UnsupportedCapabilityError(source, "order_history")
        verify_account_binding(prov, account_id)
        return fn(order_id, account_id=account_id)

    def get_order_history_dataframe(self, *args: Any, **kwargs: Any) -> pd.DataFrame:
        return models_to_dataframe(self.get_order_history(*args, **kwargs))

    def get_trades(
        self, *, source: str, symbol: str | None = None, account_id: str | None = None
    ) -> list[AccountFill]:
        prov = self._provider(source)
        caps = prov.trade_capabilities()
        _require(source, "get_trades", caps.get_trades.supported)
        fn = getattr(prov, "get_trades", None)
        if not callable(fn):
            raise UnsupportedCapabilityError(source, "get_trades")
        verify_account_binding(prov, account_id)
        return fn(symbol=symbol, account_id=account_id)

    def get_trades_dataframe(self, *args: Any, **kwargs: Any) -> pd.DataFrame:
        return models_to_dataframe(self.get_trades(*args, **kwargs))
