"""Console alert — logs to stdout."""
import logging
from .base import Alert, AlertLevel

logger = logging.getLogger("depeg-monitor")


class ConsoleAlert(Alert):
    async def send(self, level: AlertLevel, symbol: str, price: float, peg: float, source: str) -> None:
        deviation = abs(price - peg) / peg * 100
        icon = {"info": "ℹ️", "warn": "⚠️", "critical": "🚨"}.get(level.value, "")
        msg = f"{icon} [{level.value.upper()}] {symbol} at ${price:.6f} (peg ${peg}, deviation {deviation:.3f}%) via {source}"
        if level == AlertLevel.CRITICAL:
            logger.critical(msg)
        elif level == AlertLevel.WARN:
            logger.warning(msg)
        else:
            logger.info(msg)
