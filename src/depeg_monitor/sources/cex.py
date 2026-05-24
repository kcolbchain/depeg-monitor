"""CEX price sources — Binance and Coinbase public REST APIs."""
import aiohttp
from .base import PriceSource

# Symbol mapping: our symbol → exchange trading pair.
# Binance has no live DAI pair (DAIUSDT was delisted; the endpoint still
# returns 200 with price="0.00000000"), so DAI is intentionally absent here.
BINANCE_PAIRS = {"USDT": "USDCUSDT", "USDC": "USDCUSDT"}
COINBASE_PAIRS = {"USDT": "USDT-USD", "USDC": "USDC-USD", "DAI": "DAI-USD"}


class BinanceSource(PriceSource):
    name = "binance"

    def supports(self, symbol: str) -> bool:
        return symbol.upper() in BINANCE_PAIRS

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
                    # Binance returns HTTP 200 with price="0.00000000" for
                    # delisted-but-still-queryable pairs. Treat non-positive
                    # prices as unavailable to avoid phantom 100% depegs.
                    if price <= 0:
                        return None
                    # USDCUSDT returns USDC/USDT — for USDT we invert
                    if symbol.upper() == "USDT" and pair == "USDCUSDT":
                        return 1.0 / price
                    return price
        except Exception:
            return None


class CoinbaseSource(PriceSource):
    name = "coinbase"

    def supports(self, symbol: str) -> bool:
        return symbol.upper() in COINBASE_PAIRS

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
                    price = float(data["data"]["amount"])
                    if price <= 0:
                        return None
                    return price
        except Exception:
            return None
