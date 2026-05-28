"""Map normalized ``Interval`` values to provider-native strings."""

from __future__ import annotations

from collections.abc import Callable

from bandl.exceptions import ProviderError
from bandl.models.market.types import Interval


def map_interval(
    interval: Interval | str,
    mapping: dict[Interval, str],
    provider_id: str,
    *,
    normalize: Callable[[str], str] | None = None,
) -> str:
    """Resolve ``Interval`` or a native interval string using a provider mapping."""
    if isinstance(interval, Interval):
        native = mapping.get(interval)
        if native is None:
            supported = ", ".join(i.value for i in mapping)
            raise ProviderError(
                provider_id,
                f"Unsupported interval: {interval}. Supported: {supported}",
            )
        return native
    s = str(interval)
    allowed = set(mapping.values())
    if s in allowed:
        return s
    if normalize is not None:
        s_norm = normalize(s)
        if s_norm in allowed:
            return s_norm
    raise ProviderError(provider_id, f"Unsupported interval: {interval}")
