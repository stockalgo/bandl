"""Analysis bundle export tests."""

from __future__ import annotations

from bandl import Bandl
from bandl.config import BandlConfig, ProviderSettings


def test_export_bundle_structure(monkeypatch) -> None:
    client = Bandl(
        BandlConfig(
            providers={
                "coindcx": ProviderSettings(api_key="k", api_secret="s"),
            },
        ),
    )

    def fake_fills(*args, **kwargs):
        return []

    def fake_caps(source=None):
        from bandl.core.capabilities import AccountCapabilities, CapabilityDetail
        from bandl.models.account.types import Segment

        return AccountCapabilities(
            provider_id="coindcx",
            segments=[Segment.SPOT_CRYPTO],
            fills=CapabilityDetail(supported=True),
            pnl_computed=CapabilityDetail(supported=True),
        )

    client.account.get_fills = fake_fills  # type: ignore[method-assign]
    client.account.capabilities = fake_caps  # type: ignore[method-assign]
    client.account.get_orders = lambda *a, **k: []  # type: ignore[method-assign]
    client.account.get_pnl = lambda *a, **k: []  # type: ignore[method-assign]
    client.account.get_ledger_entries = lambda *a, **k: []  # type: ignore[method-assign]

    bundle = client.account.export_analysis_bundle(sources=["coindcx"])
    assert "manifest" in bundle
    assert "capabilities" in bundle
    assert "fills" in bundle
    assert bundle["manifest"]["sources"] == ["coindcx"]
