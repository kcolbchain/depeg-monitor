"""Curve stableswap pool price source — reads virtual price from Curve pools."""

from web3 import Web3
from .base import PriceSource

# Major Curve stableswap pools on Ethereum mainnet
# 3pool: USDC/USDT/DAI
CURVE_3POOL = "0xbEbc44782C7dB0a1A60Cb6fe97d0b483032FF1C7"

# Pool token addresses (for get_dy: i, j calculation)
# 3pool: [0]=DAI, [1]=USDC, [2]=USDT
CURVE_POOLS = {
    "USDC": {
        "pool": CURVE_3POOL,
        "base_idx": 1,  # USDC is token 1 in 3pool
        "quote_idx": 0,  # Quote against DAI (token 0)
        "decimals": 6,
    },
    "USDT": {
        "pool": CURVE_3POOL,
        "base_idx": 2,  # USDT is token 2 in 3pool
        "quote_idx": 0,  # Quote against DAI (token 0)
        "decimals": 6,
    },
    "DAI": {
        "pool": CURVE_3POOL,
        "base_idx": 0,  # DAI is token 0 in 3pool
        "quote_idx": 1,  # Quote against USDC (token 1)
        "decimals": 18,
    },
}

# Minimal ABI for Curve stableswap pools
CURVE_POOL_ABI = [
    {
        "inputs": [
            {"name": "i", "type": "int128"},
            {"name": "j", "type": "int128"},
            {"name": "dx", "type": "uint256"},
        ],
        "name": "get_dy",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "get_virtual_price",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"name": "i", "type": "uint256"}],
        "name": "coins",
        "outputs": [{"name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"name": "i", "type": "uint256"}],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"name": "arg0", "type": "uint256"}],
        "name": "balances",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
]


class CurvePoolSource(PriceSource):
    """Fetches stablecoin prices from Curve stableswap pools.

    Uses two methods:
    1. **get_dy**: Direct swap quote (1 base token → quote tokens). This gives
       the actual exchange rate accounting for pool imbalance.
    2. **get_virtual_price**: LP token value relative to initial deposit.
       Useful as a cross-check or fallback.
    """

    name = "curve"

    def __init__(self, rpc_url: str):
        self.w3 = Web3(Web3.HTTPProvider(rpc_url))
        self._contracts: dict[str, any] = {}

    def _get_pool_contract(self, pool_addr: str):
        """Get or create a cached pool contract instance."""
        if pool_addr not in self._contracts:
            self._contracts[pool_addr] = self.w3.eth.contract(
                address=Web3.to_checksum_address(pool_addr),
                abi=CURVE_POOL_ABI,
            )
        return self._contracts[pool_addr]

    async def get_price(self, symbol: str) -> float | None:
        """Get stablecoin price from Curve pool.

        For stablecoins, price is derived from the exchange rate against
        another stablecoin in the same pool. A perfectly balanced pool
        returns ~1.0 for all stablecoins. Deviation from 1.0 indicates
        depeg.

        Args:
            symbol: Stablecoin symbol (e.g. "USDC", "USDT", "DAI")

        Returns:
            Price relative to the quote stablecoin, or None if unavailable.
        """
        config = CURVE_POOLS.get(symbol.upper())
        if not config:
            return None

        try:
            pool = self._get_pool_contract(config["pool"])
            base_decimals = config["decimals"]

            # Use get_dy to get the actual exchange rate
            # Swap 1 unit of base token (in its native precision) to quote token
            dx = 10**base_decimals
            dy = pool.functions.get_dy(
                config["base_idx"],
                config["quote_idx"],
                dx,
            ).call()

            # Price = dy / dx, normalized by decimals
            # For same-decimal stablecoins this should be ~1.0
            quote_decimals = self._get_token_decimals(pool, config["quote_idx"])
            price = dy / 10**quote_decimals

            return price
        except Exception:
            return None

    def _get_token_decimals(self, pool_contract, idx: int) -> int:
        """Get token decimals for a pool token."""
        try:
            return pool_contract.functions.decimals(idx).call()
        except Exception:
            # Fallback: assume 18 for ERC-20 default
            return 18

    async def get_virtual_price(self, pool_addr: str) -> float | None:
        """Get the LP token virtual price (value relative to initial deposit).

        A virtual price of 1.0 means no gain/loss since pool creation.
        Useful as a depeg indicator for Curve pools.
        """
        try:
            pool = self._get_pool_contract(pool_addr)
            vp = pool.functions.get_virtual_price().call()
            # Virtual price is 1e18 precision
            return vp / 1e18
        except Exception:
            return None

    async def get_pool_balances(self, pool_addr: str) -> list[int]:
        """Get raw token balances in the pool."""
        try:
            pool = self._get_pool_contract(pool_addr)
            balances = []
            i = 0
            while True:
                try:
                    bal = pool.functions.balances(i).call()
                    balances.append(bal)
                    i += 1
                except Exception:
                    break
            return balances
        except Exception:
            return []
