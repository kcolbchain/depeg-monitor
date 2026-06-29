"""Structured alert feed — emits consensus depeg events to pluggable sinks.

A :class:`Sink` is anything that can asynchronously accept a
:class:`~depeg_monitor.events.DepegEvent`. Two sinks ship in-box:

* :class:`StdoutSink` — logs a structured line (and optional JSON) to the
  ``depeg-monitor`` logger.
* :class:`WebhookSink` — HTTP POSTs the event payload, with optional
  Slack/Discord text shaping.

:class:`AlertFeed` fans an event out to every configured sink, isolating sink
failures so one bad sink never blocks the others. New transports (Kafka, DB,
PagerDuty) only need to implement :class:`Sink` and be added to the feed.
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod

import aiohttp

from ..consensus import Severity
from ..events import DepegEvent

logger = logging.getLogger("depeg-monitor")


class Sink(ABC):
    """A pluggable destination for structured depeg events."""

    @abstractmethod
    async def emit(self, event: DepegEvent) -> None:  # pragma: no cover - interface
        ...


class StdoutSink(Sink):
    """Logs events to the standard ``depeg-monitor`` logger.

    Severity maps onto log levels so existing log routing/alerting keeps
    working. Set ``as_json=True`` to additionally emit the full structured
    payload (handy when stdout is being scraped by a log shipper).
    """

    _LEVELS = {
        Severity.NORMAL: logging.INFO,
        Severity.WATCH: logging.INFO,
        Severity.WARNING: logging.WARNING,
        Severity.CRITICAL: logging.CRITICAL,
    }

    def __init__(self, as_json: bool = False):
        self.as_json = as_json

    async def emit(self, event: DepegEvent) -> None:
        level = self._LEVELS.get(event.severity, logging.INFO)
        if self.as_json:
            logger.log(level, json.dumps(event.to_dict(), sort_keys=True))
        else:
            logger.log(level, event.headline())


class WebhookSink(Sink):
    """POSTs the structured event to a webhook URL.

    ``platform`` shapes the body for chat webhooks: ``"slack"`` → ``{"text":...}``,
    ``"discord"`` → ``{"content":...}``, anything else → the full structured
    :meth:`DepegEvent.to_dict` JSON. Delivery is best-effort: network errors are
    swallowed (and logged at debug) so a flaky endpoint can't crash the monitor.
    """

    def __init__(self, url: str, platform: str = "generic", timeout_seconds: float = 5.0):
        self.url = url
        self.platform = platform
        self.timeout_seconds = timeout_seconds

    def _payload(self, event: DepegEvent) -> dict:
        if self.platform == "slack":
            return {"text": event.headline()}
        if self.platform == "discord":
            return {"content": event.headline()}
        return event.to_dict()

    async def emit(self, event: DepegEvent) -> None:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.url,
                    json=self._payload(event),
                    timeout=aiohttp.ClientTimeout(total=self.timeout_seconds),
                ):
                    pass
        except Exception as exc:  # best-effort delivery
            logger.debug("webhook sink delivery failed: %s", exc)


class AlertFeed:
    """Dispatches consensus depeg events to all configured sinks."""

    def __init__(self, sinks: list[Sink] | None = None, min_severity: Severity = Severity.WATCH):
        self.sinks = sinks or []
        self.min_severity = min_severity

    async def publish(self, event: DepegEvent) -> bool:
        """Emit ``event`` to every sink if it meets ``min_severity``.

        Returns ``True`` if the event was published, ``False`` if it was below
        the severity floor. Each sink is isolated: a raising sink is logged and
        skipped so the remaining sinks still receive the event.
        """
        if event.severity < self.min_severity:
            return False
        for sink in self.sinks:
            try:
                await sink.emit(event)
            except Exception as exc:
                logger.error("alert sink %s failed: %s", type(sink).__name__, exc)
        return True
