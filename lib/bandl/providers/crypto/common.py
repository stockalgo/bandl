"""Shared helpers for crypto market providers."""

from __future__ import annotations

from bandl.models.market.types import AssetType

CRYPTO_ASSET_TYPES = frozenset(
    {
        AssetType.CRYPTO_SPOT,
        AssetType.CRYPTO_PERP,
        AssetType.CRYPTO_FUTURE,
    },
)


def is_crypto_asset(asset_type: AssetType) -> bool:
    """True when ``asset_type`` is a supported crypto market kind."""
    return asset_type in CRYPTO_ASSET_TYPES


def is_crypto_futures(asset_type: AssetType | None) -> bool:
    """True when the caller requests perpetual/futures market data (not spot)."""
    return asset_type in (AssetType.CRYPTO_FUTURE, AssetType.CRYPTO_PERP)
