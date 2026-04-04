"""Curve StableSwap price source.

Queries Curve pools for:
* virtual price  — the LP token's exchange rate vs. underlying
* dy (get_dy)    — the actual exchange rate between two coins in a pool
* pool balances  — individual coin balances to detect imbalances

Supports automatic pool discovery through the Curve Registry contract
and falls back to the hard-coded pool list in ``curve_pools``.
"""
from __future__ import annotations

import logging
from typing import Optional

from web3 import Web3

from .base import PriceSource
from .curve_pools import (
    CurvePoolMeta,
    KNOWN_POOLS,
    CURVE_REGISTRY_ADDRESS,
    CURVE_REGISTRY_ABI,
    pools_for_symbol,
)

logger = logging.getLogger("depeg-monitor.curve")

# ── Minimal Curve StableSwap pool ABI fragments ───────────────────

POOL_ABI = [
    {
        "name": "get_virtual_price",
        "outputs": [{"type": "uint256", "name": ""}],
        "inputs": [],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "name": "get_dy",
        "outputs": [{"type": "uint256", "name": ""}],
        "inputs": [
            {"type": "int128", "name": "i"},
            {"type": "int128", "name": "j"},
            {"type": "uint256", "name": "dx"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "name": "balances",
        "outputs": [{"type": "uint256", "name": ""}],
        "inputs": [{"type": "uint256", "name": "arg0"}],
        "stateMutability": "view",
        "type": "function",
    },
]


class CurveSource(PriceSource):
    """Fetch stablecoin prices from Curve StableSwap pools.

    Parameters
    ----------
    rpc_url:
        Ethereum JSON-RPC endpoint.
    pools:
        Optional override for pools to monitor.  When *None* the
        built-in ``KNOWN_POOLS`` registry is used.
    use_registry:
        If ``True`` attempt to discover pools via the Curve on-chain
        Registry contract (in addition to the static list).
    """

    name = "curve"

    def __init__(
        self,
        rpc_url: str,
        pools: Optional[dict[str, CurvePoolMeta]] = None,
        use_registry: bool = False,
    ):
        self.w3 = Web3(Web3.HTTPProvider(rpc_url))
        self.pools: dict[str, CurvePoolMeta] = dict(pools or KNOWN_POOLS)
        self.use_registry = use_registry

    # ── Public API (PriceSource interface) ─────────────────────────

    async def get_price(self, symbol: str) -> float | None:
        """Return the USD-equivalent price for *symbol* using Curve pools.

        Strategy:
        1. Find pools containing *symbol*.
        2. For each pool, compute get_dy for 1 unit of *symbol* → a
           reference stablecoin (USDC preferred, falling back to DAI/USDT).
        3. Return the first successful result.
        """
        candidate_pools = pools_for_symbol(symbol)
        # Also check pools loaded from registry
        for pool in self.pools.values():
            if symbol.upper() in [c.upper() for c in pool.coins] and pool not in candidate_pools:
                candidate_pools.append(pool)

        for pool in candidate_pools:
            price = self._get_dy_price(pool, symbol)
            if price is not None:
                return price

        return None

    # ── Virtual price ──────────────────────────────────────────────

    def get_virtual_price(self, pool_name: str) -> float | None:
        """Return the virtual price of an LP token (scaled to float)."""
        pool = self.pools.get(pool_name)
        if pool is None:
            return None
        try:
            contract = self._pool_contract(pool.address)
            raw = contract.functions.get_virtual_price().call()
            return raw / 1e18
        except Exception as exc:
            logger.debug("get_virtual_price failed for %s: %s", pool_name, exc)
            return None

    # ── Pool balances & imbalance detection ────────────────────────

    def get_pool_balances(self, pool_name: str) -> list[float] | None:
        """Return normalised (to 18-decimal) balances for every coin in a pool."""
        pool = self.pools.get(pool_name)
        if pool is None:
            return None
        try:
            contract = self._pool_contract(pool.address)
            balances: list[float] = []
            for idx, decimals in enumerate(pool.decimals):
                raw = contract.functions.balances(idx).call()
                balances.append(raw / (10 ** decimals))
            return balances
        except Exception as exc:
            logger.debug("get_pool_balances failed for %s: %s", pool_name, exc)
            return None

    def get_imbalance_ratio(self, pool_name: str) -> float | None:
        """Return the max/min balance ratio (1.0 = perfectly balanced)."""
        balances = self.get_pool_balances(pool_name)
        if not balances:
            return None
        min_b = min(balances)
        max_b = max(balances)
        if min_b <= 0:
            return None
        return max_b / min_b

    # ── Registry-based discovery ───────────────────────────────────

    def discover_pools_from_registry(self) -> list[str]:
        """Query the Curve Registry for pool addresses.

        Returns a list of pool addresses (as checksum strings).
        Discovered pools are *not* automatically added to ``self.pools``
        because we lack coin metadata at this stage.
        """
        try:
            registry = self.w3.eth.contract(
                address=Web3.to_checksum_address(CURVE_REGISTRY_ADDRESS),
                abi=CURVE_REGISTRY_ABI,
            )
            count = registry.functions.pool_count().call()
            addresses: list[str] = []
            for i in range(count):
                addr = registry.functions.pool_list(i).call()
                addresses.append(Web3.to_checksum_address(addr))
            return addresses
        except Exception as exc:
            logger.warning("Registry discovery failed: %s", exc)
            return []

    def get_registry_pool_coins(self, pool_address: str) -> list[str]:
        """Return coin addresses for a pool via the Registry."""
        try:
            registry = self.w3.eth.contract(
                address=Web3.to_checksum_address(CURVE_REGISTRY_ADDRESS),
                abi=CURVE_REGISTRY_ABI,
            )
            raw_coins = registry.functions.get_coins(
                Web3.to_checksum_address(pool_address)
            ).call()
            zero = "0x0000000000000000000000000000000000000000"
            return [c for c in raw_coins if c != zero]
        except Exception as exc:
            logger.debug("get_registry_pool_coins failed: %s", exc)
            return []

    def get_registry_pool_decimals(self, pool_address: str) -> list[int]:
        """Return decimals for each coin in a pool via the Registry."""
        try:
            registry = self.w3.eth.contract(
                address=Web3.to_checksum_address(CURVE_REGISTRY_ADDRESS),
                abi=CURVE_REGISTRY_ABI,
            )
            raw = registry.functions.get_decimals(
                Web3.to_checksum_address(pool_address)
            ).call()
            return [int(d) for d in raw if d > 0]
        except Exception as exc:
            logger.debug("get_registry_pool_decimals failed: %s", exc)
            return []

    # ── Internal helpers ───────────────────────────────────────────

    def _pool_contract(self, address: str):
        return self.w3.eth.contract(
            address=Web3.to_checksum_address(address),
            abi=POOL_ABI,
        )

    def _get_dy_price(self, pool: CurvePoolMeta, symbol: str) -> float | None:
        """Use get_dy to price *symbol* against a reference stablecoin."""
        upper = symbol.upper()
        coins_upper = [c.upper() for c in pool.coins]
        if upper not in coins_upper:
            return None

        i = coins_upper.index(upper)
        ref_order = ["USDC", "USDT", "DAI", "FRAX", "3CRV"]
        j: int | None = None
        for ref in ref_order:
            if ref != upper and ref in coins_upper:
                j = coins_upper.index(ref)
                break
        if j is None:
            return None

        dx = 10 ** pool.decimals[i]  # 1 unit of coin i
        try:
            contract = self._pool_contract(pool.address)
            dy = contract.functions.get_dy(i, j, dx).call()
            return dy / (10 ** pool.decimals[j])
        except Exception as exc:
            logger.debug("get_dy failed for %s in %s: %s", symbol, pool.name, exc)
            return None
