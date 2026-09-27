"""Live positions/holdings/balances/margin facet on the Bandl client."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from bandl.core.capabilities import PortfolioCapabilities
from bandl.core.dataframe import models_to_dataframe
from bandl.core.provider import PortfolioProvider
from bandl.exceptions import ConfigurationError, UnsupportedCapabilityError
from bandl.models.trading import Balance, Holding, MarginInfo, Position
from bandl.trade.validation import verify_account_binding


def _require(provider_id: str, capability: str, supported: bool) -> None:
    if not supported:
        raise UnsupportedCapabilityError(provider_id, capability)


@dataclass
class PortfolioFacet:
    client: Any

    def _provider(self, source: str) -> PortfolioProvider:
        prov = self.client._get_provider(source)
        if not isinstance(prov, PortfolioProvider):
            raise ConfigurationError(f"Provider '{source}' does not support portfolio reads")
        return prov

    def capabilities(self, source: str) -> PortfolioCapabilities:
        return self._provider(source).portfolio_capabilities()

    def supports(self, source: str, capability: str) -> bool:
        return self.capabilities(source).supports(capability)

    def get_positions(self, *, source: str, account_id: str | None = None) -> list[Position]:
        prov = self._provider(source)
        caps = prov.portfolio_capabilities()
        _require(source, "positions", caps.positions.supported)
        fn = getattr(prov, "get_positions", None)
        if not callable(fn):
            raise UnsupportedCapabilityError(source, "positions")
        verify_account_binding(prov, account_id)
        return prov.get_positions(account_id=account_id)

    def get_positions_dataframe(self, *args: Any, **kwargs: Any) -> pd.DataFrame:
        return models_to_dataframe(self.get_positions(*args, **kwargs))

    def get_holdings(self, *, source: str, account_id: str | None = None) -> list[Holding]:
        prov = self._provider(source)
        caps = prov.portfolio_capabilities()
        _require(source, "holdings", caps.holdings.supported)
        fn = getattr(prov, "get_holdings", None)
        if not callable(fn):
            raise UnsupportedCapabilityError(source, "holdings")
        verify_account_binding(prov, account_id)
        return prov.get_holdings(account_id=account_id)

    def get_holdings_dataframe(self, *args: Any, **kwargs: Any) -> pd.DataFrame:
        return models_to_dataframe(self.get_holdings(*args, **kwargs))

    def get_balances(self, *, source: str, account_id: str | None = None) -> list[Balance]:
        prov = self._provider(source)
        caps = prov.portfolio_capabilities()
        _require(source, "balances", caps.balances.supported)
        fn = getattr(prov, "get_balances", None)
        if not callable(fn):
            raise UnsupportedCapabilityError(source, "balances")
        verify_account_binding(prov, account_id)
        return prov.get_balances(account_id=account_id)

    def get_balances_dataframe(self, *args: Any, **kwargs: Any) -> pd.DataFrame:
        return models_to_dataframe(self.get_balances(*args, **kwargs))

    def get_margin(self, *, source: str, account_id: str | None = None) -> MarginInfo:
        prov = self._provider(source)
        caps = prov.portfolio_capabilities()
        _require(source, "margin", caps.margin.supported)
        fn = getattr(prov, "get_margin", None)
        if not callable(fn):
            raise UnsupportedCapabilityError(source, "margin")
        verify_account_binding(prov, account_id)
        return prov.get_margin(account_id=account_id)
