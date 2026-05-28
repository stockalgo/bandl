from __future__ import annotations

from bandl.exceptions import UnsupportedCapabilityError
from bandl.models.account.types import OrderStatus, OrderType


def require_capability(provider: str, capability: str, supported: bool) -> None:
    if not supported:
        raise UnsupportedCapabilityError(provider, capability)


_KITE_STATUS: dict[str, str] = {
    "OPEN": OrderStatus.OPEN,
    "COMPLETE": OrderStatus.COMPLETE,
    "CANCELLED": OrderStatus.CANCELLED,
    "REJECTED": OrderStatus.REJECTED,
    "TRIGGER PENDING": OrderStatus.OPEN,
    "AMO REQ RECEIVED": OrderStatus.OPEN,
}


_KITE_ORDER_TYPE: dict[str, str] = {
    "MARKET": OrderType.MARKET,
    "LIMIT": OrderType.LIMIT,
    "SL": OrderType.STOP,
    "SL-M": OrderType.STOP,
}


def map_kite_status(raw: str) -> str:
    return _KITE_STATUS.get(raw.upper(), OrderStatus.UNKNOWN)


def map_kite_order_type(raw: str) -> str:
    return _KITE_ORDER_TYPE.get(raw.upper(), OrderType.OTHER)
