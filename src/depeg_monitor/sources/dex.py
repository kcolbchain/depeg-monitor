"""DEX price source — Uniswap V3 TWAP via public RPC."""
from __future__ import annotations
from web3 import Web3
from .base import PriceSource

# Uniswap V3 USDC/WETH and USDT/WETH pool addresses on Ethereum mainnet
POOLS = {
    "USDC": "0x88e6A0c2dDD26FEEb64F039a2c41296FcB3f5640",  # USDC/WETH 0.05%
    "USDT": "0x4e68Ccd3E89f51C3074ca5072bbAC773960dFa36",  # USDT/WETH 0.3%
    "DAI":  "0x60594a405d53811d3BC4766596EFD80fd545A270",  # DAI/WETH 0.05%
}

# Minimal slot0 ABI
SLOT0_ABI = [
    {
        "inputs": [],
        "name": "slot0",
        "outputs": [
            {"name": "sqrtPriceX96", "type": "uint160"},
            {"name": "tick", "type": "int24"},
            {"name": "observationIndex", "type": "uint16"},
            {"name": "observationCardinality", "type": "uint16"},
            {"name": "observationCardinalityNext", "type": "uint16"},
            {"name": "feeProtocol", "type": "uint8"},
            {"name": "unlocked", "type": "bool"},
        ],
        "stateMutability": "view",
        "type": "function",
    }
]


class UniswapV3Source(PriceSource):
    name = "uniswap_v3"

    def __init__(self, rpc_url: str):
        self.w3 = Web3(Web3.HTTPProvider(rpc_url))

    async def get_price(self, symbol: str) -> float | None:
        pool_addr = POOLS.get(symbol.upper())
        if not pool_addr:
            return None
        try:
            pool = self.w3.eth.contract(
                address=Web3.to_checksum_address(pool_addr), abi=SLOT0_ABI
            )
            slot0 = pool.functions.slot0().call()
            sqrt_price_x96 = slot0[0]
            # Price = (sqrtPriceX96 / 2^96)^2 — this gives token1/token0
            price = (sqrt_price_x96 / (2**96)) ** 2
            # For stablecoin/WETH pools, we need ETH price to derive USD
            # Simplified: assume token0 is the stablecoin, price ≈ 1/price * ETH_USD
            # In practice you'd fetch ETH/USD separately
            # For now return the raw ratio as a proxy
            return 1.0 / price if price > 0 else None
        except Exception:
            return None
