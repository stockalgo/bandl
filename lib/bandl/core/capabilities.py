from __future__ import annotations

from pydantic import BaseModel, Field

from bandl.models.account.types import Segment


class CapabilityDetail(BaseModel):
    model_config = {"extra": "forbid"}

    supported: bool = False
    max_history_days: int | None = None
    pagination: str | None = None
    notes: list[str] = Field(default_factory=list)


class AccountCapabilities(BaseModel):
    model_config = {"extra": "forbid"}

    provider_id: str
    segments: list[Segment] = Field(default_factory=list)
    orders: CapabilityDetail = Field(default_factory=CapabilityDetail)
    fills: CapabilityDetail = Field(default_factory=CapabilityDetail)
    ledger: CapabilityDetail = Field(default_factory=CapabilityDetail)
    pnl_broker: CapabilityDetail = Field(default_factory=CapabilityDetail)
    pnl_computed: CapabilityDetail = Field(default_factory=CapabilityDetail)

    def supports(self, capability: str) -> bool:
        detail = getattr(self, capability, None)
        if isinstance(detail, CapabilityDetail):
            return detail.supported
        return False


class TradeCapabilities(BaseModel):
    model_config = {"extra": "forbid"}

    provider_id: str
    segments: list[Segment] = Field(default_factory=list)
    place: CapabilityDetail = Field(default_factory=CapabilityDetail)
    modify: CapabilityDetail = Field(default_factory=CapabilityDetail)
    cancel: CapabilityDetail = Field(default_factory=CapabilityDetail)
    get_open_orders: CapabilityDetail = Field(default_factory=CapabilityDetail)
    get_order: CapabilityDetail = Field(default_factory=CapabilityDetail)
    get_trades: CapabilityDetail = Field(default_factory=CapabilityDetail)

    def supports(self, capability: str) -> bool:
        detail = getattr(self, capability, None)
        if isinstance(detail, CapabilityDetail):
            return detail.supported
        return False


class PortfolioCapabilities(BaseModel):
    model_config = {"extra": "forbid"}

    provider_id: str
    segments: list[Segment] = Field(default_factory=list)
    positions: CapabilityDetail = Field(default_factory=CapabilityDetail)
    holdings: CapabilityDetail = Field(default_factory=CapabilityDetail)
    balances: CapabilityDetail = Field(default_factory=CapabilityDetail)
    margin: CapabilityDetail = Field(default_factory=CapabilityDetail)

    def supports(self, capability: str) -> bool:
        detail = getattr(self, capability, None)
        if isinstance(detail, CapabilityDetail):
            return detail.supported
        return False
