"""Shared validation helpers for broker trading execution."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from bandl.exceptions import ConfigurationError, InvalidOrderError, UnsupportedCapabilityError
from bandl.models.account.types import OrderType
from bandl.models.trading.order import OrderRequest, QuantityUnit
from bandl.models.trading.types import Validity


def extract_broker_order_id(raw_id: Any) -> str | None:
    """Validate and extract a clean order ID string from a broker response.

    Rejects booleans (True/False), mappings, sequences, and empty or sentinel strings
    ('None', 'null', 'undefined', 'true', 'false'). Returns the stripped string ID or None.
    """
    if isinstance(raw_id, bool) or not isinstance(raw_id, (str, int)):
        return None
    cleaned = str(raw_id).strip()
    if not cleaned or cleaned.lower() in ("none", "null", "undefined", "true", "false"):
        return None
    return cleaned


def resolve_account_binding(
    provider: Any,
    account_id: str | None = None,
    order_account_id: str | None = None,
) -> str | None:
    """Resolve account identity assertion against provider binding.

    Any two supplied identities disagreeing raises ConfigurationError.
    An explicit request ID without a known binding raises ConfigurationError.
    When no request ID is supplied, returns the configured binding or None.
    """
    provider_id = getattr(provider, "provider_id", str(provider))
    bound = getattr(provider, "bound_account_id", None)

    if account_id is not None and order_account_id is not None and account_id != order_account_id:
        raise ConfigurationError(
            f"Conflicting account_id argument '{account_id}' and order.account_id "
            f"'{order_account_id}'"
        )
    supplied = account_id if account_id is not None else order_account_id
    if supplied is not None:
        if bound is None:
            raise ConfigurationError(
                f"Provider '{provider_id}' has no known bound account to match assertion "
                f"'{supplied}'"
            )
        if bound != supplied:
            raise ConfigurationError(
                f"Supplied account_id '{supplied}' does not match bound account '{bound}'"
            )
        return bound
    return bound


def verify_account_binding(provider: Any, account_id: str | None) -> None:
    """Verify that a caller-supplied account_id matches the provider's bound account."""
    resolve_account_binding(provider, account_id=account_id)


def validate_broker_order_request(provider_id: str, order: OrderRequest) -> None:
    """Validate common broker constraints before instrument lookup or mutation dispatch."""
    # Quantity unit compatibility: only BASE is supported by Dhan/Zerodha
    if order.quantity_unit != QuantityUnit.BASE:
        raise UnsupportedCapabilityError(
            provider_id,
            "quantity_unit",
            message=(
                f"quantity_unit '{order.quantity_unit.value}' is not supported by {provider_id}; "
                "only BASE is supported"
            ),
        )

    # Unsupported order options on these adapters
    if order.reduce_only:
        raise UnsupportedCapabilityError(
            provider_id, "reduce_only", message=f"reduce_only is not supported by {provider_id}"
        )
    if order.post_only:
        raise UnsupportedCapabilityError(
            provider_id, "post_only", message=f"post_only is not supported by {provider_id}"
        )
    if order.position_side is not None:
        raise UnsupportedCapabilityError(
            provider_id,
            "position_side",
            message=f"position_side is not supported by {provider_id}",
        )
    if bool(order.extra):
        raise UnsupportedCapabilityError(
            provider_id,
            "extra",
            message=f"extra options are not supported by {provider_id}",
        )

    # Market parameter validation: reject unsupported markets like crypto
    if order.market is not None:
        norm_market = order.market.strip().lower()
        if norm_market not in ("equity", "in_equity"):
            raise UnsupportedCapabilityError(
                provider_id,
                "market",
                message=f"market '{order.market}' is not supported by {provider_id}",
            )

    # Native integer quantity enforcement
    if order.quantity % 1 != 0:
        raise InvalidOrderError(
            provider_id,
            f"{provider_id} requires integer share/lot quantity, got {order.quantity}",
        )

    # Required price/trigger price for specific order types
    if order.order_type in (OrderType.LIMIT, OrderType.STOP_LIMIT) and order.price is None:
        raise InvalidOrderError(
            provider_id, f"{order.order_type.value.upper()} orders require price"
        )
    if order.order_type in (OrderType.STOP, OrderType.STOP_LIMIT) and order.trigger_price is None:
        raise InvalidOrderError(
            provider_id, f"{order.order_type.value.upper()} orders require trigger_price"
        )

    # Disclosed quantity validation
    if order.disclosed_quantity is not None and order.disclosed_quantity > 0:
        if order.disclosed_quantity % 1 != 0:
            raise InvalidOrderError(
                provider_id,
                f"{provider_id} requires integer disclosed_quantity, "
                f"got {order.disclosed_quantity}",
            )
        if order.disclosed_quantity > order.quantity:
            raise InvalidOrderError(
                provider_id,
                f"disclosed_quantity ({order.disclosed_quantity}) cannot exceed total quantity "
                f"({order.quantity})",
            )

    # Client order id (tag / correlationId) constraints
    if order.client_order_id is not None:
        if not order.client_order_id.strip():
            raise InvalidOrderError(
                provider_id, "client_order_id cannot be empty or whitespace-only"
            )
        max_len = 20 if provider_id == "zerodha" else 30
        if len(order.client_order_id) > max_len:
            label = "Zerodha tag" if provider_id == "zerodha" else "Dhan correlationId"
            raise InvalidOrderError(
                provider_id,
                f"{label} (client_order_id) length cannot exceed {max_len} characters, "
                f"got {len(order.client_order_id)}",
            )


def validate_order_modification(
    provider_id: str,
    *,
    price: Decimal | None = None,
    trigger_price: Decimal | None = None,
    quantity: Decimal | None = None,
    validity: Validity | str | None = None,
    supported_validities: set[Validity] | None = None,
) -> None:
    """Centralized validation for order modification requests."""
    if price is None and trigger_price is None and quantity is None and validity is None:
        raise InvalidOrderError(
            provider_id, "Order modification requires at least one parameter to modify"
        )

    if quantity is not None:
        if not isinstance(quantity, Decimal):
            try:
                quantity = Decimal(str(quantity))
            except Exception as err:
                raise InvalidOrderError(
                    provider_id, f"Invalid modification quantity: {quantity}"
                ) from err
        if not quantity.is_finite() or quantity <= 0:
            raise InvalidOrderError(
                provider_id,
                f"Modification quantity must be finite and positive, got {quantity}",
            )
        if quantity % 1 != 0:
            raise InvalidOrderError(
                provider_id,
                f"{provider_id} requires integer modification quantity, got {quantity}",
            )

    if price is not None:
        if not isinstance(price, Decimal):
            try:
                price = Decimal(str(price))
            except Exception as err:
                raise InvalidOrderError(
                    provider_id, f"Invalid modification price: {price}"
                ) from err
        if not price.is_finite() or price <= 0:
            raise InvalidOrderError(
                provider_id,
                f"Modification price must be finite and positive, got {price}",
            )

    if trigger_price is not None:
        if not isinstance(trigger_price, Decimal):
            try:
                trigger_price = Decimal(str(trigger_price))
            except Exception as err:
                raise InvalidOrderError(
                    provider_id, f"Invalid modification trigger_price: {trigger_price}"
                ) from err
        if not trigger_price.is_finite() or trigger_price <= 0:
            raise InvalidOrderError(
                provider_id,
                f"Modification trigger_price must be finite and positive, got {trigger_price}",
            )

    if validity is not None:
        val_enum: Validity | None = None
        if isinstance(validity, Validity):
            val_enum = validity
        elif isinstance(validity, str):
            try:
                val_enum = Validity(validity.lower())
            except ValueError:
                pass
        valid_set = supported_validities or {Validity.DAY, Validity.IOC}
        if val_enum is None or val_enum not in valid_set:
            raise InvalidOrderError(
                provider_id, f"Unsupported or invalid validity for modification: {validity}"
            )


def validate_lot_size(
    provider_id: str,
    quantity: Decimal,
    lot_size: Decimal | int | None,
) -> None:
    """Validate quantity is a positive multiple of lot_size."""
    if lot_size is None:
        return
    lot_dec = Decimal(str(lot_size))
    if lot_dec <= 0:
        return
    if (quantity % lot_dec) != 0:
        raise InvalidOrderError(
            provider_id,
            f"Quantity {quantity} must be a multiple of lot size {lot_size}",
        )


def validate_tick_size(
    provider_id: str,
    price: Decimal | None,
    tick_size: Decimal | float | None,
    field_name: str = "price",
) -> None:
    """Validate price/trigger_price is a multiple of tick_size."""
    if price is None or tick_size is None:
        return
    tick_dec = Decimal(str(tick_size))
    if tick_dec <= 0:
        return
    # Use remainder check; handles e.g. Decimal("100.03") % Decimal("0.05") != 0
    rem = price % tick_dec
    if rem != 0 and rem != tick_dec:
        raise InvalidOrderError(
            provider_id,
            f"{field_name} {price} must be a multiple of tick size {tick_size}",
        )
