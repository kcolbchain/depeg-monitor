"""Tests for the CEX price sources."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from depeg_monitor.sources.cex import (
    BINANCE_PAIRS,
    COINBASE_PAIRS,
    BinanceSource,
    CoinbaseSource,
)


def _mock_aiohttp_session(json_payload: dict, status: int = 200):
    """Build a MagicMock that behaves like an aiohttp.ClientSession."""
    response = MagicMock()
    response.status = status
    response.json = AsyncMock(return_value=json_payload)
    response.__aenter__ = AsyncMock(return_value=response)
    response.__aexit__ = AsyncMock(return_value=False)

    session = MagicMock()
    session.get = MagicMock(return_value=response)
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return session


class TestBinanceSource:
    def test_supports_only_mapped_symbols(self):
        src = BinanceSource()
        assert src.supports("USDC")
        assert src.supports("USDT")
        # Binance has no live DAI pair — must report False so monitor coverage
        # log makes that explicit instead of silently no-op'ing each cycle.
        assert not src.supports("DAI")

    def test_dai_not_in_binance_map(self):
        """Regression guard for the delisted DAIUSDT pair."""
        assert "DAI" not in BINANCE_PAIRS

    @pytest.mark.asyncio
    async def test_zero_price_returns_none(self):
        """Delisted pairs return HTTP 200 with price='0.00000000' — not a depeg."""
        session = _mock_aiohttp_session({"symbol": "USDCUSDT", "price": "0.00000000"})
        with patch("depeg_monitor.sources.cex.aiohttp.ClientSession", return_value=session):
            price = await BinanceSource().get_price("USDC")
        assert price is None

    @pytest.mark.asyncio
    async def test_negative_price_returns_none(self):
        session = _mock_aiohttp_session({"symbol": "USDCUSDT", "price": "-1.0"})
        with patch("depeg_monitor.sources.cex.aiohttp.ClientSession", return_value=session):
            price = await BinanceSource().get_price("USDC")
        assert price is None

    @pytest.mark.asyncio
    async def test_valid_price_passes_through(self):
        session = _mock_aiohttp_session({"symbol": "USDCUSDT", "price": "1.00093"})
        with patch("depeg_monitor.sources.cex.aiohttp.ClientSession", return_value=session):
            price = await BinanceSource().get_price("USDC")
        assert price == pytest.approx(1.00093)

    @pytest.mark.asyncio
    async def test_usdt_inversion(self):
        """USDT is priced as 1 / USDCUSDT — but only when USDCUSDT > 0."""
        session = _mock_aiohttp_session({"symbol": "USDCUSDT", "price": "1.00093"})
        with patch("depeg_monitor.sources.cex.aiohttp.ClientSession", return_value=session):
            price = await BinanceSource().get_price("USDT")
        assert price == pytest.approx(1.0 / 1.00093)


class TestCoinbaseSource:
    def test_supports_dai(self):
        # Coinbase still lists DAI-USD — this is the fallback that keeps DAI
        # covered after Binance was dropped.
        assert CoinbaseSource().supports("DAI")

    def test_unsupported_symbol(self):
        assert not CoinbaseSource().supports("BTC")

    @pytest.mark.asyncio
    async def test_zero_price_returns_none(self):
        session = _mock_aiohttp_session(
            {"data": {"amount": "0", "base": "DAI", "currency": "USD"}}
        )
        with patch("depeg_monitor.sources.cex.aiohttp.ClientSession", return_value=session):
            price = await CoinbaseSource().get_price("DAI")
        assert price is None

    @pytest.mark.asyncio
    async def test_offpeg_price_passes_through_and_triggers_critical(self):
        """A genuine depeg (0.92) must NOT be filtered like the 0/negative
        sentinels — it is a positive, finite price the source reports faithfully,
        and the monitor must classify it as CRITICAL.

        Guards the boundary between "non-positive sentinel → None" (a delisted
        pair) and "small positive price → real depeg the alert path must see".
        Wires the *real* CoinbaseSource into a DepegMonitor so the off-peg price
        flows source → threshold comparator → alert dispatcher end to end.
        """
        from depeg_monitor.alerts.base import Alert, AlertLevel
        from depeg_monitor.config import AlertsConfig, MonitorConfig, StablecoinConfig
        from depeg_monitor.monitor import DepegMonitor

        class CapturingAlert(Alert):
            def __init__(self):
                self.calls = []

            async def send(self, level, symbol, price, peg, source):
                self.calls.append((level, symbol, price, source))

        session = _mock_aiohttp_session(
            {"data": {"amount": "0.92", "base": "DAI", "currency": "USD"}}
        )
        source = CoinbaseSource()
        with patch("depeg_monitor.sources.cex.aiohttp.ClientSession", return_value=session):
            price = await source.get_price("DAI")
            assert price == pytest.approx(0.92)  # off-peg, but a valid price

            alert = CapturingAlert()
            monitor = DepegMonitor(
                MonitorConfig(
                    stablecoins=[StablecoinConfig(symbol="DAI")],  # 1% critical default
                    alerts=AlertsConfig(console=False),
                )
            )
            monitor.sources = [source]
            monitor.alerts = [alert]
            await monitor.check_once()

        assert len(alert.calls) == 1
        level, symbol, alert_price, alert_source = alert.calls[0]
        assert level == AlertLevel.CRITICAL
        assert symbol == "DAI"
        assert alert_price == pytest.approx(0.92)
        assert alert_source == "coinbase"
