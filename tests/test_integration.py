"""Integration tests with mock price feeds (issue #4).

Tests the full monitoring pipeline:
  mock source → threshold comparator → alert dispatcher

Scenarios covered:
  1. Normal operations — prices within threshold, no alerts
  2. Warn-level depeg — deviation >= warn_threshold but < critical
  3. Critical-level depeg — deviation >= critical_threshold
  4. Recovery — depeg followed by price returning to peg
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.depeg_monitor.monitor import DepegMonitor
from src.depeg_monitor.config import (
    MonitorConfig,
    StablecoinConfig,
    SourcesConfig,
    DexSourceConfig,
    AlertsConfig,
)
from src.depeg_monitor.sources.base import PriceSource
from src.depeg_monitor.alerts.base import Alert, AlertLevel


# --- Mock Price Sources ---


class MockPriceSource(PriceSource):
    """Controllable mock source for testing."""

    def __init__(self, name: str, prices: dict[str, float]):
        self._name = name
        self._prices = prices
        self.call_count = 0

    async def get_price(self, symbol: str) -> float | None:
        self.call_count += 1
        return self._prices.get(symbol)

    @property
    def name(self) -> str:
        return self._name


class FailingPriceSource(PriceSource):
    """Source that always returns None (simulates outage)."""

    @property
    def name(self) -> str:
        return "failing-source"

    async def get_price(self, symbol: str) -> float | None:
        return None


# --- Mock Alert Dispatcher ---


class MockAlert(Alert):
    """Captures alert calls for assertion."""

    def __init__(self):
        self.calls: list[dict] = []

    async def send(self, level: AlertLevel, symbol: str, price: float, peg: float, source: str) -> None:
        self.calls.append({
            "level": level,
            "symbol": symbol,
            "price": price,
            "peg": peg,
            "source": source,
        })


# --- Fixtures ---


@pytest.fixture
def mock_alert():
    return MockAlert()


@pytest.fixture
def normal_config():
    """Config with a single USDC stablecoin and default thresholds."""
    return MonitorConfig(
        stablecoins=[StablecoinConfig(
            symbol="USDC",
            peg=1.0,
            warn_threshold=0.005,    # 0.5%
            critical_threshold=0.01,  # 1.0%
        )],
        alerts=AlertsConfig(console=False),
    )


@pytest.fixture
def monitor_with_mocks(normal_config, mock_alert):
    """Create a DepegMonitor with injected mock source and alert."""
    mon = DepegMonitor(normal_config)
    mon.sources = [MockPriceSource("mock-cex", {"USDC": 1.0})]
    mon.alerts = [mock_alert]
    return mon


# --- Test: Normal Operations ---


@pytest.mark.asyncio
async def test_normal_ops_no_alerts(monitor_with_mocks, mock_alert):
    """Prices within threshold should produce zero alerts."""
    monitor = monitor_with_mocks
    monitor.sources = [MockPriceSource("mock-cex", {"USDC": 0.999})]

    await monitor.check_once()

    assert len(mock_alert.calls) == 0


@pytest.mark.asyncio
async def test_normal_ops_exact_peg(monitor_with_mocks, mock_alert):
    """Price exactly at peg should produce zero alerts."""
    monitor = monitor_with_mocks
    monitor.sources = [MockPriceSource("mock-cex", {"USDC": 1.0})]

    await monitor.check_once()

    assert len(mock_alert.calls) == 0


@pytest.mark.asyncio
async def test_normal_ops_slight_deviation(monitor_with_mocks, mock_alert):
    """Deviation below warn_threshold (0.5%) should not alert."""
    monitor = monitor_with_mocks
    # 0.003 = 0.3% deviation, below 0.5% warn threshold
    monitor.sources = [MockPriceSource("mock-cex", {"USDC": 1.003})]

    await monitor.check_once()

    assert len(mock_alert.calls) == 0


# --- Test: Warn-Level Depeg ---


@pytest.mark.asyncio
async def test_warn_level_depeg_above(monitor_with_mocks, mock_alert):
    """Price at 0.7% deviation should trigger a WARN alert."""
    monitor = monitor_with_mocks
    # 0.993 = 0.7% below peg, above 0.5% warn threshold
    monitor.sources = [MockPriceSource("mock-cex", {"USDC": 0.993})]

    await monitor.check_once()

    assert len(mock_alert.calls) == 1
    assert mock_alert.calls[0]["level"] == AlertLevel.WARN
    assert mock_alert.calls[0]["symbol"] == "USDC"
    assert mock_alert.calls[0]["price"] == 0.993
    assert mock_alert.calls[0]["source"] == "mock-cex"


@pytest.mark.asyncio
async def test_warn_level_depeg_below_peg(monitor_with_mocks, mock_alert):
    """Price above peg at warn level should also trigger WARN."""
    monitor = monitor_with_mocks
    monitor.sources = [MockPriceSource("mock-cex", {"USDC": 1.007})]

    await monitor.check_once()

    assert len(mock_alert.calls) == 1
    assert mock_alert.calls[0]["level"] == AlertLevel.WARN


# --- Test: Critical-Level Depeg ---


@pytest.mark.asyncio
async def test_critical_level_depeg(monitor_with_mocks, mock_alert):
    """Price at 2% deviation should trigger CRITICAL alert."""
    monitor = monitor_with_mocks
    monitor.sources = [MockPriceSource("mock-cex", {"USDC": 0.98})]

    await monitor.check_once()

    assert len(mock_alert.calls) == 1
    assert mock_alert.calls[0]["level"] == AlertLevel.CRITICAL
    assert mock_alert.calls[0]["symbol"] == "USDC"
    assert mock_alert.calls[0]["price"] == 0.98


@pytest.mark.asyncio
async def test_critical_above_peg(monitor_with_mocks, mock_alert):
    """Price above peg at critical level should trigger CRITICAL."""
    monitor = monitor_with_mocks
    monitor.sources = [MockPriceSource("mock-cex", {"USDC": 1.02})]

    await monitor.check_once()

    assert len(mock_alert.calls) == 1
    assert mock_alert.calls[0]["level"] == AlertLevel.CRITICAL


# --- Test: Recovery ---


@pytest.mark.asyncio
async def test_recovery_no_alert_after_fix(monitor_with_mocks, mock_alert):
    """After a critical depeg, returning to normal should not alert."""
    monitor = monitor_with_mocks

    # Cycle 1: critical depeg
    monitor.sources = [MockPriceSource("mock-cex", {"USDC": 0.95})]
    await monitor.check_once()
    assert len(mock_alert.calls) == 1
    assert mock_alert.calls[0]["level"] == AlertLevel.CRITICAL

    # Cycle 2: recovery to normal
    monitor.sources = [MockPriceSource("mock-cex", {"USDC": 1.001})]
    await monitor.check_once()

    # Only 1 alert total (from cycle 1), no new alert on recovery
    assert len(mock_alert.calls) == 1


# --- Test: Source Failure ---


@pytest.mark.asyncio
async def test_source_failure_no_crash(monitor_with_mocks, mock_alert):
    """A failing source should not crash the monitor or produce alerts."""
    monitor = monitor_with_mocks
    monitor.sources = [FailingPriceSource()]

    await monitor.check_once()  # Should not raise

    assert len(mock_alert.calls) == 0


@pytest.mark.asyncio
async def test_mixed_sources_one_fails(monitor_with_mocks, mock_alert):
    """If one source fails but another returns critical, alert should fire."""
    monitor = monitor_with_mocks
    monitor.sources = [
        FailingPriceSource(),
        MockPriceSource("working-cex", {"USDC": 0.97}),
    ]

    await monitor.check_once()

    assert len(mock_alert.calls) == 1
    assert mock_alert.calls[0]["level"] == AlertLevel.CRITICAL
    assert mock_alert.calls[0]["source"] == "working-cex"


# --- Test: Multiple Stablecoins ---


@pytest.mark.asyncio
async def test_multiple_stablecoins(mock_alert):
    """Each stablecoin is checked independently."""
    config = MonitorConfig(
        stablecoins=[
            StablecoinConfig(symbol="USDC", warn_threshold=0.005, critical_threshold=0.01),
            StablecoinConfig(symbol="USDT", warn_threshold=0.005, critical_threshold=0.01),
            StablecoinConfig(symbol="DAI", warn_threshold=0.005, critical_threshold=0.01),
        ],
        alerts=AlertsConfig(console=False),
    )
    mon = DepegMonitor(config)
    mon.sources = [MockPriceSource("mock-cex", {
        "USDC": 0.993,  # warn
        "USDT": 0.98,   # critical
        "DAI": 1.0,     # normal
    })]
    mon.alerts = [mock_alert]

    await mon.check_once()

    # USDC warn + USDT critical = 2 alerts
    assert len(mock_alert.calls) == 2
    symbols = {c["symbol"] for c in mock_alert.calls}
    assert symbols == {"USDC", "USDT"}

    # Verify correct levels
    for call in mock_alert.calls:
        if call["symbol"] == "USDC":
            assert call["level"] == AlertLevel.WARN
        elif call["symbol"] == "USDT":
            assert call["level"] == AlertLevel.CRITICAL


# --- Test: Threshold Boundary ---


@pytest.mark.asyncio
async def test_exact_warn_boundary(monitor_with_mocks, mock_alert):
    """Price exactly at warn_threshold boundary should trigger WARN."""
    monitor = monitor_with_mocks
    # 0.5% below = exactly at warn_threshold
    monitor.sources = [MockPriceSource("mock-cex", {"USDC": 0.995})]

    await monitor.check_once()

    assert len(mock_alert.calls) == 1
    assert mock_alert.calls[0]["level"] == AlertLevel.WARN


@pytest.mark.asyncio
async def test_exact_critical_boundary(monitor_with_mocks, mock_alert):
    """Price exactly at critical_threshold should trigger CRITICAL."""
    monitor = monitor_with_mocks
    # 1% below = exactly at critical_threshold
    monitor.sources = [MockPriceSource("mock-cex", {"USDC": 0.99})]

    await monitor.check_once()

    assert len(mock_alert.calls) == 1
    assert mock_alert.calls[0]["level"] == AlertLevel.CRITICAL
