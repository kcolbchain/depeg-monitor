"""Core monitoring loop."""

import asyncio
import logging
from typing import Sequence
from aiohttp import web

from .config import MonitorConfig, StablecoinConfig
from .sources.base import PriceSource
from .sources.cex import BinanceSource, CoinbaseSource
from .sources.dex import UniswapV3Source
from .sources.curve import CurvePoolSource
from .alerts.base import Alert, AlertLevel
from .alerts.console import ConsoleAlert
from .alerts.webhook import WebhookAlert
from .alerts.telegram import TelegramAlert
from .database_alert import DatabaseAlert

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
        sources.append(CurvePoolSource(self.config.sources.dex.rpc_url))
        return sources

    def _build_alerts(self) -> list[Alert]:
        alerts: list[Alert] = []
        if self.config.alerts.console:
            alerts.append(ConsoleAlert())
        if self.config.alerts.discord_webhook:
            alerts.append(WebhookAlert(self.config.alerts.discord_webhook, "discord"))
        if self.config.alerts.slack_webhook:
            alerts.append(WebhookAlert(self.config.alerts.slack_webhook, "slack"))
        if self.config.alerts.telegram_bot_token and self.config.alerts.telegram_chat_id:
            alerts.append(
                TelegramAlert(
                    self.config.alerts.telegram_bot_token,
                    self.config.alerts.telegram_chat_id,
                )
            )
        if self.config.alerts.db_path:
            alerts.append(DatabaseAlert(self.config.alerts.db_path))
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
                continue
            for alert in self.alerts:
                await alert.send(level, coin.symbol, price, coin.peg, source.name)

    def _log_coverage(self) -> None:
        symbols = [c.symbol for c in self.config.stablecoins]
        for source in self.sources:
            covered = [s for s in symbols if source.supports(s)]
            label = ", ".join(covered) if covered else "(none)"
            logger.info(f"  {source.name:<11} \u2192 {label}")

    async def run(self) -> None:
        logger.info(f"Starting depeg-monitor \u2014 checking every {self.config.interval_seconds}s")
        logger.info(f"Watching: {', '.join(c.symbol for c in self.config.stablecoins)}")
        logger.info(f"Sources: {', '.join(s.name for s in self.sources)}")
        logger.info("Source coverage:")
        self._log_coverage()

        health_app = web.Application()
        health_app.router.add_get("/health", self._handle_health)
        health_port = getattr(self.config, "health_port", 8080)
        health_runner = web.AppRunner(health_app)
        await health_runner.setup()
        health_site = web.TCPSite(health_runner, "127.0.0.1", health_port)
        await health_site.start()
        logger.info(f"Health endpoint listening on 127.0.0.1:{health_port}/health")

        while True:
            try:
                await self.check_once()
            except Exception as e:
                logger.error(f"Monitor cycle error: {e}")
            await asyncio.sleep(self.config.interval_seconds)

    async def _handle_health(self, request: web.Request) -> web.Response:
        return web.json_response(
            {"status": "ok", "service": "depeg-monitor", "checks": len(self.sources)}
        )
