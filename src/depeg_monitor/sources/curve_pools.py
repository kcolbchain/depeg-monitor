"""Curve StableSwap pool registry and configuration.

Known pool addresses, coin metadata, and helpers for pool discovery
via the Curve Registry contract.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CurvePoolMeta:
    """Metadata for a single Curve StableSwap pool."""

    name: str
    address: str
    coins: list[str] = field(default_factory=list)
    coin_addresses: list[str] = field(default_factory=list)
    decimals: list[int] = field(default_factory=list)
    pool_type: str = "stable"  # "stable" | "crypto" | "meta"
    lp_token: str = ""


# ── Well-known Ethereum mainnet pools ──────────────────────────────

THREE_POOL = CurvePoolMeta(
    name="3pool",
    address="0xbEbc44782C7dB0a1A60Cb6fe97d0b483032FF1C7",
    coins=["DAI", "USDC", "USDT"],
    coin_addresses=[
        "0x6B175474E89094C44Da98b954EedeAC495271d0F",  # DAI
        "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",  # USDC
        "0xdAC17F958D2ee523a2206206994597C13D831ec7",  # USDT
    ],
    decimals=[18, 6, 6],
    pool_type="stable",
    lp_token="0x6c3F90f043a72FA612cbac8115EE7e52BDe6E490",
)

FRAX_USDC_POOL = CurvePoolMeta(
    name="frax_usdc",
    address="0xDcEF968d416a41Cdac0ED8702fAC8128A64241A2",
    coins=["FRAX", "USDC"],
    coin_addresses=[
        "0x853d955aCEf822Db058eb8505911ED77F175b99e",  # FRAX
        "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",  # USDC
    ],
    decimals=[18, 6],
    pool_type="stable",
    lp_token="0x3175Df0976dFA876431C2E9eE6Bc45b65d3473CC",
)

LUSD_3CRV_POOL = CurvePoolMeta(
    name="lusd_3crv",
    address="0xEd279fDD11cA84bEef15AF5D39BB4d4bEE23F0cA",
    coins=["LUSD", "3Crv"],
    coin_addresses=[
        "0x5f98805A4E8be255a32880FDeC7F6728C6568bA0",  # LUSD
        "0x6c3F90f043a72FA612cbac8115EE7e52BDe6E490",  # 3Crv LP
    ],
    decimals=[18, 18],
    pool_type="meta",
    lp_token="0xEd279fDD11cA84bEef15AF5D39BB4d4bEE23F0cA",
)

USDD_3CRV_POOL = CurvePoolMeta(
    name="usdd_3crv",
    address="0xe6b5CC1B4b47305c58392CE3D359B10282FC36Ea",
    coins=["USDD", "3Crv"],
    coin_addresses=[
        "0x0C10bF8FcB7Bf5412187A595ab97a3609160b5c6",  # USDD
        "0x6c3F90f043a72FA612cbac8115EE7e52BDe6E490",  # 3Crv LP
    ],
    decimals=[18, 18],
    pool_type="meta",
    lp_token="0xe6b5CC1B4b47305c58392CE3D359B10282FC36Ea",
)

# Quick lookup by name
KNOWN_POOLS: dict[str, CurvePoolMeta] = {
    p.name: p
    for p in [THREE_POOL, FRAX_USDC_POOL, LUSD_3CRV_POOL, USDD_3CRV_POOL]
}

# Map stablecoin symbols to pools that contain them
SYMBOL_TO_POOLS: dict[str, list[CurvePoolMeta]] = {}
for _pool in KNOWN_POOLS.values():
    for _coin in _pool.coins:
        SYMBOL_TO_POOLS.setdefault(_coin.upper(), []).append(_pool)


def pools_for_symbol(symbol: str) -> list[CurvePoolMeta]:
    """Return all known pools that include *symbol*."""
    return SYMBOL_TO_POOLS.get(symbol.upper(), [])


# ── Curve on-chain Registry ABI (minimal) ─────────────────────────

CURVE_REGISTRY_ADDRESS = "0x90E00ACe148ca3b23Ac1bC8C240C2a7Dd9c2d7f5"

CURVE_REGISTRY_ABI = [
    {
        "name": "pool_count",
        "outputs": [{"type": "uint256", "name": ""}],
        "inputs": [],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "name": "pool_list",
        "outputs": [{"type": "address", "name": ""}],
        "inputs": [{"type": "uint256", "name": "_index"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "name": "get_coins",
        "outputs": [{"type": "address[8]", "name": ""}],
        "inputs": [{"type": "address", "name": "_pool"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "name": "get_n_coins",
        "outputs": [{"type": "uint256[2]", "name": ""}],
        "inputs": [{"type": "address", "name": "_pool"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "name": "get_decimals",
        "outputs": [{"type": "uint256[8]", "name": ""}],
        "inputs": [{"type": "address", "name": "_pool"}],
        "stateMutability": "view",
        "type": "function",
    },
]
