"""CEX price sources — Binance and Coinbase public REST APIs."""
import aiohttp
from .base import PriceSource

# Symbol mapping: our symbol → exchange trading pair
BINANCE_PAIRS = {"USDT": "USDCUSDT", "USDC": "USDCUSDT", "DAI": "DAIUSDT"}
COINBASE_PAIRS = {"USDT": "USDT-USD", "USDC": "USDC-USD", "DAI": "DAI-USD"}


class BinanceSource(PriceSource):
    name = "binance"

    async def get_price(self, symbol: str) -> float | None:
        pair = BINANCE_PAIRS.get(symbol.upper())
        if not pair:
            return None
        url = f"https://api.binance.com/api/v3/ticker/price?symbol={pair}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status != 200:
                        return None
                    data = await resp.json()
                    price = float(data["price"])
                    # USDCUSDT returns USDC/USDT — for USDT we invert
                    if symbol.upper() == "USDT" and pair == "USDCUSDT":
                        return 1.0 / price if price > 0 else None
                    return price
        except Exception:
            return None


class CoinbaseSource(PriceSource):
    name = "coinbase"

    async def get_price(self, symbol: str) -> float | None:
        pair = COINBASE_PAIRS.get(symbol.upper())
        if not pair:
            return None
        url = f"https://api.coinbase.com/v2/prices/{pair}/spot"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status != 200:
                        return None
                    data = await resp.json()
                    return float(data["data"]["amount"])
        except Exception:
            return None
