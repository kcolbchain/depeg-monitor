"""Webhook alert — Discord, Slack, or generic HTTP POST."""
import aiohttp
from .base import Alert, AlertLevel


class WebhookAlert(Alert):
    def __init__(self, url: str, platform: str = "generic"):
        self.url = url
        self.platform = platform  # "discord", "slack", or "generic"

    async def send(self, level: AlertLevel, symbol: str, price: float, peg: float, source: str) -> None:
        deviation = abs(price - peg) / peg * 100
        text = f"[{level.value.upper()}] {symbol} at ${price:.6f} (deviation {deviation:.3f}%) via {source}"

        if self.platform == "discord":
            payload = {"content": text}
        elif self.platform == "slack":
            payload = {"text": text}
        else:
            payload = {"level": level.value, "symbol": symbol, "price": price, "peg": peg, "deviation": deviation, "source": source, "message": text}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(self.url, json=payload, timeout=aiohttp.ClientTimeout(total=5)):
                    pass
        except Exception:
            pass  # Alert delivery is best-effort
