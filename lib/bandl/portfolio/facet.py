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

    def get_positions(self, *, source: str) -> list[Position]:
        prov = self._provider(source)
        caps = prov.portfolio_capabilities()
        _require(source, "positions", caps.positions.supported)
        return prov.get_positions()

    def get_positions_dataframe(self, *args: Any, **kwargs: Any) -> pd.DataFrame:
        return models_to_dataframe(self.get_positions(*args, **kwargs))

    def get_holdings(self, *, source: str) -> list[Holding]:
        prov = self._provider(source)
        caps = prov.portfolio_capabilities()
        _require(source, "holdings", caps.holdings.supported)
        return prov.get_holdings()

    def get_holdings_dataframe(self, *args: Any, **kwargs: Any) -> pd.DataFrame:
        return models_to_dataframe(self.get_holdings(*args, **kwargs))

    def get_balances(self, *, source: str) -> list[Balance]:
        prov = self._provider(source)
        caps = prov.portfolio_capabilities()
        _require(source, "balances", caps.balances.supported)
        return prov.get_balances()

    def get_balances_dataframe(self, *args: Any, **kwargs: Any) -> pd.DataFrame:
        return models_to_dataframe(self.get_balances(*args, **kwargs))

    def get_margin(self, *, source: str) -> MarginInfo:
        prov = self._provider(source)
        caps = prov.portfolio_capabilities()
        _require(source, "margin", caps.margin.supported)
        return prov.get_margin()
