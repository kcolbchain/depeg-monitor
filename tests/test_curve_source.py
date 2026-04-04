"""Comprehensive tests for the Curve StableSwap price source.

All web3 contract calls are mocked — no network access required.
"""
from __future__ import annotations

import asyncio
import pytest
from unittest.mock import MagicMock, patch, PropertyMock

from depeg_monitor.sources.curve import CurveSource, POOL_ABI
from depeg_monitor.sources.curve_pools import (
    CurvePoolMeta,
    KNOWN_POOLS,
    THREE_POOL,
    FRAX_USDC_POOL,
    LUSD_3CRV_POOL,
    USDD_3CRV_POOL,
    SYMBOL_TO_POOLS,
    CURVE_REGISTRY_ADDRESS,
    pools_for_symbol,
)


# ── helpers ────────────────────────────────────────────────────────

def _run(coro):
    """Run an async coroutine synchronously."""
    return asyncio.get_event_loop().run_until_complete(coro)


def _make_source(pools=None, rpc_url="http://localhost:8545", use_registry=False):
    """Create a CurveSource with a mocked Web3 provider."""
    with patch("depeg_monitor.sources.curve.Web3") as MockWeb3:
        mock_w3 = MagicMock()
        MockWeb3.return_value = mock_w3
        MockWeb3.HTTPProvider.return_value = MagicMock()
        MockWeb3.to_checksum_address = lambda addr: addr
        source = CurveSource(rpc_url, pools=pools, use_registry=use_registry)
        # Re-assign the mock so tests can configure it
        source.w3 = mock_w3
        mock_w3.eth.contract.return_value = MagicMock()
    return source


def _setup_get_dy(source, dy_value):
    """Configure mock so get_dy returns *dy_value*."""
    mock_contract = MagicMock()
    mock_contract.functions.get_dy.return_value.call.return_value = dy_value
    source.w3.eth.contract.return_value = mock_contract
    return mock_contract


def _setup_virtual_price(source, vp_value):
    mock_contract = MagicMock()
    mock_contract.functions.get_virtual_price.return_value.call.return_value = vp_value
    source.w3.eth.contract.return_value = mock_contract
    return mock_contract


def _setup_balances(source, balances_list):
    """Configure mock so balances(idx) returns values from the list."""
    mock_contract = MagicMock()
    mock_contract.functions.balances.side_effect = lambda idx: MagicMock(
        call=MagicMock(return_value=balances_list[idx])
    )
    source.w3.eth.contract.return_value = mock_contract
    return mock_contract


# ══════════════════════════════════════════════════════════════════
# 1. curve_pools module
# ══════════════════════════════════════════════════════════════════


class TestCurvePools:
    """Tests for pool registry / config module."""

    def test_known_pools_contains_3pool(self):
        assert "3pool" in KNOWN_POOLS
        assert KNOWN_POOLS["3pool"] is THREE_POOL

    def test_known_pools_contains_frax(self):
        assert "frax_usdc" in KNOWN_POOLS
        assert KNOWN_POOLS["frax_usdc"] is FRAX_USDC_POOL

    def test_three_pool_metadata(self):
        assert THREE_POOL.coins == ["DAI", "USDC", "USDT"]
        assert THREE_POOL.decimals == [18, 6, 6]
        assert THREE_POOL.pool_type == "stable"
        assert THREE_POOL.address.startswith("0x")

    def test_frax_pool_metadata(self):
        assert FRAX_USDC_POOL.coins == ["FRAX", "USDC"]
        assert FRAX_USDC_POOL.decimals == [18, 6]

    def test_lusd_pool_is_meta_type(self):
        assert LUSD_3CRV_POOL.pool_type == "meta"

    def test_symbol_to_pools_usdc(self):
        pools = SYMBOL_TO_POOLS.get("USDC", [])
        assert any(p.name == "3pool" for p in pools)
        assert any(p.name == "frax_usdc" for p in pools)

    def test_pools_for_symbol_dai(self):
        pools = pools_for_symbol("DAI")
        assert len(pools) >= 1
        assert any(p.name == "3pool" for p in pools)

    def test_pools_for_symbol_unknown(self):
        assert pools_for_symbol("XYZ") == []

    def test_pools_for_symbol_case_insensitive(self):
        assert pools_for_symbol("usdc") == pools_for_symbol("USDC")


# ══════════════════════════════════════════════════════════════════
# 2. CurveSource — instantiation
# ══════════════════════════════════════════════════════════════════


class TestCurveSourceInit:
    def test_name_is_curve(self):
        source = _make_source()
        assert source.name == "curve"

    def test_default_pools_are_known_pools(self):
        source = _make_source()
        assert set(source.pools.keys()) == set(KNOWN_POOLS.keys())

    def test_custom_pools_override(self):
        custom = {"test": THREE_POOL}
        source = _make_source(pools=custom)
        assert list(source.pools.keys()) == ["test"]


# ══════════════════════════════════════════════════════════════════
# 3. CurveSource.get_price — get_dy based pricing
# ══════════════════════════════════════════════════════════════════


class TestGetPrice:
    def test_get_price_usdc_via_3pool(self):
        source = _make_source()
        # 1 USDC (1e6) → should return ~1e6 USDT (index 2 in 3pool)
        _setup_get_dy(source, 999_800)  # 0.9998 USDT
        price = _run(source.get_price("USDC"))
        assert price is not None
        assert abs(price - 0.9998) < 1e-6

    def test_get_price_dai_via_3pool(self):
        source = _make_source()
        # DAI → USDC; DAI is index 0, USDC is index 1 in 3pool
        _setup_get_dy(source, 1_000_100)  # 1.0001 USDC
        price = _run(source.get_price("DAI"))
        assert price is not None
        assert abs(price - 1.0001) < 1e-6

    def test_get_price_usdt(self):
        source = _make_source()
        _setup_get_dy(source, 999_950)  # ~1.0 USDC
        price = _run(source.get_price("USDT"))
        assert price is not None
        assert 0.9 < price < 1.1

    def test_get_price_unknown_symbol(self):
        source = _make_source()
        price = _run(source.get_price("XYZ"))
        assert price is None

    def test_get_price_contract_reverts(self):
        source = _make_source()
        mock_contract = MagicMock()
        mock_contract.functions.get_dy.return_value.call.side_effect = Exception("revert")
        source.w3.eth.contract.return_value = mock_contract
        price = _run(source.get_price("USDC"))
        assert price is None

    def test_get_price_case_insensitive(self):
        source = _make_source()
        _setup_get_dy(source, 1_000_000)
        price = _run(source.get_price("usdc"))
        assert price is not None


# ══════════════════════════════════════════════════════════════════
# 4. Virtual price
# ══════════════════════════════════════════════════════════════════


class TestVirtualPrice:
    def test_virtual_price_3pool(self):
        source = _make_source()
        # 1.02e18
        _setup_virtual_price(source, 1_020_000_000_000_000_000)
        vp = source.get_virtual_price("3pool")
        assert vp is not None
        assert abs(vp - 1.02) < 1e-6

    def test_virtual_price_unknown_pool(self):
        source = _make_source()
        assert source.get_virtual_price("nonexistent") is None

    def test_virtual_price_contract_error(self):
        source = _make_source()
        mock_contract = MagicMock()
        mock_contract.functions.get_virtual_price.return_value.call.side_effect = Exception("err")
        source.w3.eth.contract.return_value = mock_contract
        assert source.get_virtual_price("3pool") is None


# ══════════════════════════════════════════════════════════════════
# 5. Pool balances / imbalance
# ══════════════════════════════════════════════════════════════════


class TestPoolBalances:
    def test_get_pool_balances_3pool(self):
        source = _make_source()
        # DAI(18dec), USDC(6dec), USDT(6dec)
        raw = [
            200_000 * 10**18,   # 200k DAI
            200_000 * 10**6,    # 200k USDC
            200_000 * 10**6,    # 200k USDT
        ]
        _setup_balances(source, raw)
        balances = source.get_pool_balances("3pool")
        assert balances is not None
        assert len(balances) == 3
        for b in balances:
            assert abs(b - 200_000) < 1

    def test_get_pool_balances_unknown_pool(self):
        source = _make_source()
        assert source.get_pool_balances("nonexistent") is None

    def test_imbalance_ratio_balanced(self):
        source = _make_source()
        raw = [100 * 10**18, 100 * 10**6, 100 * 10**6]
        _setup_balances(source, raw)
        ratio = source.get_imbalance_ratio("3pool")
        assert ratio is not None
        assert abs(ratio - 1.0) < 0.01

    def test_imbalance_ratio_imbalanced(self):
        source = _make_source()
        # DAI heavily overweight
        raw = [500 * 10**18, 100 * 10**6, 100 * 10**6]
        _setup_balances(source, raw)
        ratio = source.get_imbalance_ratio("3pool")
        assert ratio is not None
        assert ratio >= 4.9

    def test_imbalance_ratio_unknown_pool(self):
        source = _make_source()
        assert source.get_imbalance_ratio("nonexistent") is None

    def test_imbalance_ratio_zero_balance(self):
        source = _make_source()
        raw = [0, 100 * 10**6, 100 * 10**6]
        _setup_balances(source, raw)
        ratio = source.get_imbalance_ratio("3pool")
        assert ratio is None


# ══════════════════════════════════════════════════════════════════
# 6. Registry-based discovery
# ══════════════════════════════════════════════════════════════════


class TestRegistryDiscovery:
    def test_discover_pools(self):
        source = _make_source(use_registry=True)
        mock_registry = MagicMock()
        mock_registry.functions.pool_count.return_value.call.return_value = 2
        mock_registry.functions.pool_list.side_effect = lambda i: MagicMock(
            call=MagicMock(return_value=f"0x{'0' * 39}{i}")
        )
        source.w3.eth.contract.return_value = mock_registry
        pools = source.discover_pools_from_registry()
        assert len(pools) == 2

    def test_discover_pools_failure(self):
        source = _make_source(use_registry=True)
        source.w3.eth.contract.side_effect = Exception("RPC down")
        pools = source.discover_pools_from_registry()
        assert pools == []

    def test_get_registry_pool_coins(self):
        source = _make_source(use_registry=True)
        zero = "0x0000000000000000000000000000000000000000"
        coins = [
            "0x6B175474E89094C44Da98b954EedeAC495271d0F",
            "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
            zero, zero, zero, zero, zero, zero,
        ]
        mock_registry = MagicMock()
        mock_registry.functions.get_coins.return_value.call.return_value = coins
        source.w3.eth.contract.return_value = mock_registry
        result = source.get_registry_pool_coins("0xbEbc44782C7dB0a1A60Cb6fe97d0b483032FF1C7")
        assert len(result) == 2

    def test_get_registry_pool_decimals(self):
        source = _make_source(use_registry=True)
        raw_decimals = [18, 6, 6, 0, 0, 0, 0, 0]
        mock_registry = MagicMock()
        mock_registry.functions.get_decimals.return_value.call.return_value = raw_decimals
        source.w3.eth.contract.return_value = mock_registry
        result = source.get_registry_pool_decimals("0xbEbc44782C7dB0a1A60Cb6fe97d0b483032FF1C7")
        assert result == [18, 6, 6]


# ══════════════════════════════════════════════════════════════════
# 7. Integration with monitor
# ══════════════════════════════════════════════════════════════════


class TestMonitorIntegration:
    def test_curve_source_registered_in_monitor(self):
        """CurveSource should appear in monitor.sources after import update."""
        from depeg_monitor.sources import CurveSource as CS
        assert CS is CurveSource

    def test_source_implements_interface(self):
        from depeg_monitor.sources.base import PriceSource
        assert issubclass(CurveSource, PriceSource)

    def test_source_has_name_property(self):
        source = _make_source()
        assert isinstance(source.name, str)
        assert source.name == "curve"
