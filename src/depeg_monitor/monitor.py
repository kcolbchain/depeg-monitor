"""Core monitoring loop."""

import asyncio
import logging
from typing import Sequence

from .config import MonitorConfig, StablecoinConfig
from .sources.base import PriceSource
from .sources.cex import BinanceSource, CoinbaseSource
from .sources.dex import UniswapV3Source
from .sources.curve import CurvePoolSource
from .alerts.base import Alert, AlertLevel
from .alerts.console import ConsoleAlert
from .alerts.webhook import WebhookAlert
from .alerts.telegram import TelegramAlert
from .alerts.feed import AlertFeed, Sink, StdoutSink, WebhookSink
from .consensus import ConsensusThresholds, Severity, SourceReading, compute_consensus
from .database_alert import DatabaseAlert
from .events import DepegEvent

logger = logging.getLogger("depeg-monitor")


def _severity_floor(name: str) -> Severity:
    return {
        "watch": Severity.WATCH,
        "warning": Severity.WARNING,
        "critical": Severity.CRITICAL,
    }.get(name.lower(), Severity.WATCH)


class DepegMonitor:
    def __init__(self, config: MonitorConfig):
        self.config = config
        self.sources = self._build_sources()
        self.alerts = self._build_alerts()
        self.consensus_thresholds = self._build_consensus_thresholds()
        self.alert_feed = self._build_alert_feed()

    def _build_sources(self) -> list[PriceSource]:
        sources: list[PriceSource] = []
        for cex in self.config.sources.cex:
            if cex == "binance":
                sources.append(BinanceSource())
            elif cex == "coinbase":
                sources.append(CoinbaseSource())
        sources.append(UniswapV3Source(self.config.sources.dex.rpc_url))
        # Curve pool source (same RPC)
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
        # Telegram alert support
        if self.config.alerts.telegram_bot_token and self.config.alerts.telegram_chat_id:
            alerts.append(
                TelegramAlert(
                    self.config.alerts.telegram_bot_token,
                    self.config.alerts.telegram_chat_id,
                )
            )
        # SQLite event logging
        if self.config.alerts.db_path:
            alerts.append(DatabaseAlert(self.config.alerts.db_path))
        return alerts

    def _build_consensus_thresholds(self) -> ConsensusThresholds:
        c = self.config.consensus
        return ConsensusThresholds(
            watch_bps=c.watch_bps,
            warning_bps=c.warning_bps,
            critical_bps=c.critical_bps,
            min_agreement=c.min_agreement,
        )

    def _build_alert_feed(self) -> AlertFeed:
        c = self.config.consensus
        sinks: list[Sink] = []
        if c.stdout_sink:
            sinks.append(StdoutSink(as_json=c.stdout_json))
        if c.webhook_url:
            sinks.append(WebhookSink(c.webhook_url, platform=c.webhook_platform))
        return AlertFeed(sinks, min_severity=_severity_floor(c.min_emit_severity))

    async def check_once(self) -> None:
        for coin in self.config.stablecoins:
            if self.config.consensus.enabled:
                await self._check_coin_consensus(coin)
            else:
                await self._check_coin(coin)

    async def _gather_readings(self, coin: StablecoinConfig) -> list[SourceReading]:
        """Collect one reading per source for ``coin`` this cycle.

        Unavailable sources (``get_price`` returns ``None`` or raises) are simply
        omitted; ``compute_consensus`` then filters non-positive/non-finite
        prices, so the consensus is built only from venues that genuinely
        reported a usable price this cycle.
        """
        readings: list[SourceReading] = []
        for source in self.sources:
            try:
                price = await source.get_price(coin.symbol)
            except Exception as exc:
                logger.debug("source %s failed for %s: %s", source.name, coin.symbol, exc)
                continue
            if price is None:
                continue
            readings.append(SourceReading(source.name, price))
        return readings

    async def _check_coin_consensus(self, coin: StablecoinConfig) -> DepegEvent | None:
        """Aggregate all sources into a consensus peg and publish a depeg event.

        Returns the published :class:`DepegEvent` (useful for tests), or ``None``
        when there was no data or the consensus was within the healthy band.
        """
        readings = await self._gather_readings(coin)
        result = compute_consensus(coin.symbol, coin.peg, readings, self.consensus_thresholds)
        if result is None or not result.is_depeg:
            return None
        event = DepegEvent.from_consensus(result)
        published = await self.alert_feed.publish(event)
        return event if published else None

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

    def _log_coverage(self) -> None:
        """Log which (source × stablecoin) pairs will actually be exercised.

        Each source's ``supports(symbol)`` decides whether that pair shows up;
        a source with no overlap is still in the list but will be a no-op for
        the configured symbols. Surfacing this on startup catches misconfigs
        like a delisted exchange pair without waiting for the first cycle.
        """
        symbols = [c.symbol for c in self.config.stablecoins]
        for source in self.sources:
            covered = [s for s in symbols if source.supports(s)]
            label = ", ".join(covered) if covered else "(none)"
            logger.info(f"  {source.name:<11} → {label}")

    async def run(self) -> None:
        logger.info(f"Starting depeg-monitor — checking every {self.config.interval_seconds}s")
        logger.info(f"Watching: {', '.join(c.symbol for c in self.config.stablecoins)}")
        logger.info(f"Sources: {', '.join(s.name for s in self.sources)}")
        logger.info("Source coverage:")
        self._log_coverage()

        while True:
            try:
                await self.check_once()
            except Exception as e:
                logger.error(f"Monitor cycle error: {e}")
            await asyncio.sleep(self.config.interval_seconds)
