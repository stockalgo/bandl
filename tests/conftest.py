"""Global pytest configuration and fixtures for bandl test suite."""

from __future__ import annotations

import httpx
import pytest


@pytest.fixture(autouse=True)
def guard_execution_network(
    monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> None:
    """Prevent unmocked HTTP network access during offline execution contract tests."""
    if "integration" in request.keywords or "test_execution_contracts" not in request.node.nodeid:
        return

    orig_init = httpx.Client.__init__

    def guarded_init(self: httpx.Client, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        transport = kwargs.get("transport")
        if transport is None:

            def disallow_network(req: httpx.Request) -> httpx.Response:
                raise RuntimeError(
                    f"Unexpected unmocked real network call during offline execution tests: "
                    f"{req.method} {req.url}"
                )

            kwargs["transport"] = httpx.MockTransport(disallow_network)
        orig_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.Client, "__init__", guarded_init)
