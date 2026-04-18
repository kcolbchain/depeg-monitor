"""Tests for Curve pool price source."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from depeg_monitor.sources.curve import CurvePoolSource, CURVE_POOLS, CURVE_3POOL


@pytest.fixture
def mock_w3():
    """Create a mock Web3 instance."""
    with patch("depeg_monitor.sources.curve.Web3") as mock_web3_cls:
        mock_w3 = MagicMock()
        mock_web3_cls.return_value = mock_w3
        source = CurvePoolSource("https://eth.llamarpc.com")
        yield source, mock_w3


class TestCurvePoolSource:
    def test_name(self):
        source = CurvePoolSource("https://rpc.example.com")
        assert source.name == "curve"

    def test_supported_symbols(self):
        assert "USDC" in CURVE_POOLS
        assert "USDT" in CURVE_POOLS
        assert "DAI" in CURVE_POOLS

    @pytest.mark.asyncio
    async def test_get_price_usdc_balanced_pool(self, mock_w3):
        """USDC price from a balanced pool should be ~1.0."""
        source, mock_w3 = mock_w3

        # Mock get_dy: 1 USDC (1e6) → 1.0001 DAI (1.0001e18)
        mock_pool = MagicMock()
        mock_pool.functions.get_dy.return_value.call.return_value = 1000100000000000000  # 1.0001 DAI in 18 decimals
        mock_pool.functions.decimals.return_value.call.return_value = 18
        mock_w3.eth.contract.return_value = mock_pool

        price = await source.get_price("USDC")
        assert price is not None
        assert abs(price - 1.0001) < 1e-10

    @pytest.mark.asyncio
    async def test_get_price_usdt(self, mock_w3):
        """USDT price should use correct pool indices."""
        source, mock_w3 = mock_w3

        mock_pool = MagicMock()
        mock_pool.functions.get_dy.return_value.call.return_value = 999500000000000000  # 0.9995 DAI
        mock_pool.functions.decimals.return_value.call.return_value = 18
        mock_w3.eth.contract.return_value = mock_pool

        price = await source.get_price("USDT")
        assert price is not None
        assert abs(price - 0.9995) < 1e-10

    @pytest.mark.asyncio
    async def test_get_price_dai(self, mock_w3):
        """DAI price should quote against USDC."""
        source, mock_w3 = mock_w3

        mock_pool = MagicMock()
        mock_pool.functions.get_dy.return_value.call.return_value = 1000000  # 1.0 USDC in 6 decimals
        mock_pool.functions.decimals.return_value.call.return_value = 6
        mock_w3.eth.contract.return_value = mock_pool

        price = await source.get_price("DAI")
        assert price is not None
        assert abs(price - 1.0) < 1e-10

    @pytest.mark.asyncio
    async def test_get_price_unsupported_symbol(self, mock_w3):
        """Unsupported symbol should return None."""
        source, _ = mock_w3
        price = await source.get_price("BTC")
        assert price is None

    @pytest.mark.asyncio
    async def test_get_price_rpc_error(self, mock_w3):
        """RPC errors should return None gracefully."""
        source, mock_w3 = mock_w3

        mock_pool = MagicMock()
        mock_pool.functions.get_dy.return_value.call.side_effect = Exception("RPC timeout")
        mock_w3.eth.contract.return_value = mock_pool

        price = await source.get_price("USDC")
        assert price is None

    @pytest.mark.asyncio
    async def test_get_virtual_price(self, mock_w3):
        """Virtual price from a healthy pool should be ~1.0+."""
        source, mock_w3 = mock_w3

        mock_pool = MagicMock()
        mock_pool.functions.get_virtual_price.return_value.call.return_value = 1020000000000000000  # 1.02
        mock_w3.eth.contract.return_value = mock_pool

        vp = await source.get_virtual_price(CURVE_3POOL)
        assert vp is not None
        assert abs(vp - 1.02) < 1e-10

    @pytest.mark.asyncio
    async def test_get_virtual_price_error(self, mock_w3):
        """Virtual price error should return None."""
        source, mock_w3 = mock_w3

        mock_pool = MagicMock()
        mock_pool.functions.get_virtual_price.return_value.call.side_effect = Exception("error")
        mock_w3.eth.contract.return_value = mock_pool

        vp = await source.get_virtual_price(CURVE_3POOL)
        assert vp is None

    @pytest.mark.asyncio
    async def test_get_pool_balances(self, mock_w3):
        """Pool balances should return list of token balances."""
        source, mock_w3 = mock_w3

        mock_pool = MagicMock()
        # Return balances for 3 tokens, then fail on 4th
        mock_pool.functions.balances.return_value.call.side_effect = [
            100000000000000000000000,  # DAI: 100k
            100000000,  # USDC: 100k (6 decimals)
            100000000,  # USDT: 100k (6 decimals)
            Exception("no more tokens"),
        ]
        mock_w3.eth.contract.return_value = mock_pool

        balances = await source.get_pool_balances(CURVE_3POOL)
        assert len(balances) == 3
        assert balances[0] == 100000000000000000000000
        assert balances[1] == 100000000

    @pytest.mark.asyncio
    async def test_pool_contract_caching(self, mock_w3):
        """Same pool address should reuse contract instance."""
        source, mock_w3 = mock_w3

        mock_pool = MagicMock()
        mock_pool.functions.get_dy.return_value.call.return_value = 1000000000000000000
        mock_pool.functions.decimals.return_value.call.return_value = 18
        mock_w3.eth.contract.return_value = mock_pool

        await source.get_price("USDC")
        await source.get_price("USDT")

        # Should only create contract once (same pool)
        assert mock_w3.eth.contract.call_count == 1

    def test_pool_config_consistency(self):
        """Pool configurations should reference valid indices."""
        for symbol, config in CURVE_POOLS.items():
            assert config["pool"] == CURVE_3POOL, f"{symbol}: should use 3pool"
            assert config["base_idx"] in (0, 1, 2), f"{symbol}: invalid base_idx"
            assert config["quote_idx"] in (0, 1, 2), f"{symbol}: invalid quote_idx"
            assert config["base_idx"] != config["quote_idx"], f"{symbol}: base and quote must differ"
