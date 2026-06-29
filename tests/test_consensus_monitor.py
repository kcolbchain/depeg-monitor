"""Integration tests for the consensus-mode monitor path.

Wires real(ish) mock sources into a DepegMonitor running in consensus mode and
asserts that per-source readings are aggregated into a single structured depeg
event published through the alert feed.
"""

import pytest

from depeg_monitor.alerts.feed import AlertFeed, Sink
from depeg_monitor.config import ConsensusFeedConfig, MonitorConfig, StablecoinConfig
from depeg_monitor.consensus import Severity
from depeg_monitor.events import DepegEvent
from depeg_monitor.monitor import DepegMonitor
from depeg_monitor.sources.base import PriceSource


class MockSource(PriceSource):
    def __init__(self, name: str, price: float | None):
        self._name = name
        self._price = price

    @property
    def name(self) -> str:
        return self._name

    async def get_price(self, symbol: str) -> float | None:
        return self._price


class RaisingSource(PriceSource):
    @property
    def name(self) -> str:
        return "boom"

    async def get_price(self, symbol: str) -> float | None:
        raise RuntimeError("rpc down")


class CapturingSink(Sink):
    def __init__(self):
        self.events: list[DepegEvent] = []

    async def emit(self, event: DepegEvent) -> None:
        self.events.append(event)


def _monitor(price_map: dict[str, float | None], **consensus_kwargs) -> tuple[DepegMonitor, CapturingSink]:
    config = MonitorConfig(
        stablecoins=[StablecoinConfig(symbol="USDC", peg=1.0)],
        consensus=ConsensusFeedConfig(enabled=True, stdout_sink=False, **consensus_kwargs),
    )
    monitor = DepegMonitor(config)
    monitor.sources = [MockSource(name, price) for name, price in price_map.items()]
    sink = CapturingSink()
    monitor.alert_feed = AlertFeed([sink], min_severity=monitor.alert_feed.min_severity)
    return monitor, sink


@pytest.mark.asyncio
async def test_consensus_mode_emits_single_event_for_clear_depeg():
    # Three venues all near 0.97 -> one CRITICAL consensus event, not three.
    monitor, sink = _monitor({"binance": 0.970, "coinbase": 0.971, "curve": 0.969})
    await monitor.check_once()

    assert len(sink.events) == 1
    event = sink.events[0]
    assert event.symbol == "USDC"
    assert event.severity == Severity.CRITICAL
    assert event.sources_used == 3
    assert set(event.sources) == {"binance", "coinbase", "curve"}


@pytest.mark.asyncio
async def test_consensus_mode_silent_when_healthy():
    monitor, sink = _monitor({"binance": 1.0, "coinbase": 1.0001, "curve": 0.9999})
    await monitor.check_once()
    assert sink.events == []


@pytest.mark.asyncio
async def test_consensus_mode_ignores_unavailable_and_raising_sources():
    monitor, sink = _monitor({"binance": 0.95, "coinbase": None})
    # Add a source that raises — must be skipped, not crash the cycle.
    monitor.sources.append(RaisingSource())
    await monitor.check_once()

    assert len(sink.events) == 1
    # Only the venue that returned a usable price contributes.
    assert sink.events[0].sources == ("binance",)


@pytest.mark.asyncio
async def test_consensus_mode_returns_none_when_no_data():
    monitor, _ = _monitor({"binance": None, "coinbase": None})
    coin = monitor.config.stablecoins[0]
    assert await monitor._check_coin_consensus(coin) is None


@pytest.mark.asyncio
async def test_consensus_mode_respects_min_emit_severity():
    # A small (watch-level) deviation is suppressed when the floor is critical.
    monitor, sink = _monitor(
        {"binance": 0.9973, "coinbase": 0.9972, "curve": 0.9974},
        min_emit_severity="critical",
    )
    coin = monitor.config.stablecoins[0]
    result = await monitor._check_coin_consensus(coin)
    assert result is None
    assert sink.events == []


@pytest.mark.asyncio
async def test_per_source_mode_unchanged_when_consensus_disabled():
    # Default config (consensus disabled) must keep the legacy per-source path:
    # two off-peg sources => two alerts via the legacy Alert channels.
    from depeg_monitor.alerts.base import Alert, AlertLevel

    class CapturingAlert(Alert):
        def __init__(self):
            self.calls = []

        async def send(self, level, symbol, price, peg, source):
            self.calls.append((level, source))

    config = MonitorConfig(
        stablecoins=[StablecoinConfig(symbol="USDC", peg=1.0)],
    )
    assert config.consensus.enabled is False
    monitor = DepegMonitor(config)
    monitor.sources = [MockSource("a", 0.95), MockSource("b", 0.96)]
    alert = CapturingAlert()
    monitor.alerts = [alert]

    await monitor.check_once()

    assert len(alert.calls) == 2
    assert all(level == AlertLevel.CRITICAL for level, _ in alert.calls)
