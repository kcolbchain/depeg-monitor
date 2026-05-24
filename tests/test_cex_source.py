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
