"""Core monitoring loop."""
import asyncio
import logging
from typing import Sequence

from .config import MonitorConfig, StablecoinConfig
from .sources.base import PriceSource
from .sources.cex import BinanceSource, CoinbaseSource
from .sources.dex import UniswapV3Source
from .sources.curve import CurveSource
from .alerts.base import Alert, AlertLevel
from .alerts.console import ConsoleAlert
from .alerts.webhook import WebhookAlert

logger = logging.getLogger("depeg-monitor")


class DepegMonitor:
    def __init__(self, config: MonitorConfig):
        self.config = config
        self.sources = self._build_sources()
        self.alerts = self._build_alerts()

    def _build_sources(self) -> list[PriceSource]:
        sources: list[PriceSource] = []
        for cex in self.config.sources.cex:
            if cex == "binance":
                sources.append(BinanceSource())
            elif cex == "coinbase":
                sources.append(CoinbaseSource())
        sources.append(UniswapV3Source(self.config.sources.dex.rpc_url))
        sources.append(CurveSource(self.config.sources.dex.rpc_url))
        return sources

    def _build_alerts(self) -> list[Alert]:
        alerts: list[Alert] = []
        if self.config.alerts.console:
            alerts.append(ConsoleAlert())
        if self.config.alerts.discord_webhook:
            alerts.append(WebhookAlert(self.config.alerts.discord_webhook, "discord"))
        if self.config.alerts.slack_webhook:
            alerts.append(WebhookAlert(self.config.alerts.slack_webhook, "slack"))
        return alerts

    async def check_once(self) -> None:
        for coin in self.config.stablecoins:
            await self._check_coin(coin)

    async def _check_coin(self, coin: StablecoinConfig) -> None:
        for source in self.sources:
            price = await source.get_price(coin.symbol)
            if price is None:
                continue

            deviation = abs(price - coin.peg) / coin.peg

            if deviation >= coin.critical_threshold:
                level = AlertLevel.CRITICAL
            elif deviation >= coin.warn_threshold:
                level = AlertLevel.WARN
            else:
                continue  # Within normal range

            for alert in self.alerts:
                await alert.send(level, coin.symbol, price, coin.peg, source.name)

    async def run(self) -> None:
        logger.info(f"Starting depeg-monitor — checking every {self.config.interval_seconds}s")
        logger.info(f"Watching: {', '.join(c.symbol for c in self.config.stablecoins)}")
        logger.info(f"Sources: {', '.join(s.name for s in self.sources)}")

        while True:
            try:
                await self.check_once()
            except Exception as e:
                logger.error(f"Monitor cycle error: {e}")
            await asyncio.sleep(self.config.interval_seconds)
