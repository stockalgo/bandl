"""Provider registry."""

from __future__ import annotations

from typing import Any


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, Any] = {}

    def register(self, provider_id: str, instance: Any) -> None:
        self._providers[provider_id] = instance

    def get(self, provider_id: str) -> Any:
        if provider_id not in self._providers:
            raise KeyError(f"Unknown provider: {provider_id}")
        return self._providers[provider_id]

    def list_providers(self) -> list[str]:
        return sorted(self._providers.keys())
