"""Pure helpers used by the depeg-monitor fuzz harness.

The monitor's live loop is async and network-backed. These helpers keep the
price-tick, threshold, and aggregation invariants testable without touching
external exchanges.
"""

from __future__ import annotations

import json
import math
import statistics
from dataclasses import dataclass
from typing import Iterable, Mapping

from .alerts.base import AlertLevel


class TickParseError(ValueError):
    """Raised when a raw price tick cannot be normalized safely."""


@dataclass(frozen=True)
class PriceTick:
    symbol: str
    price: float
    timestamp: int
    source: str = "unknown"


def parse_price_tick(payload: bytes | str | Mapping[str, object]) -> PriceTick:
    """Parse a raw tick payload into a finite positive price observation."""
    if isinstance(payload, bytes):
        try:
            payload = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise TickParseError("tick payload is not utf-8") from exc

    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise TickParseError("tick payload is not valid json") from exc

    if not isinstance(payload, Mapping):
        raise TickParseError("tick payload must be an object")

    symbol = str(payload.get("symbol", "")).strip().upper()
    source = str(payload.get("source", "unknown")).strip() or "unknown"

    try:
        price = float(payload["price"])
        timestamp = int(payload.get("timestamp", payload.get("ts", 0)))
    except (KeyError, TypeError, ValueError) as exc:
        raise TickParseError("tick payload has invalid price or timestamp") from exc

    if not symbol:
        raise TickParseError("tick payload is missing symbol")
    if not math.isfinite(price) or price <= 0:
        raise TickParseError("tick price must be finite and positive")
    if timestamp < 0:
        raise TickParseError("tick timestamp must be non-negative")

    return PriceTick(symbol=symbol, price=price, timestamp=timestamp, source=source)


def validate_thresholds(peg: float, warn_threshold: float, critical_threshold: float) -> None:
    values = (peg, warn_threshold, critical_threshold)
    if not all(math.isfinite(value) for value in values):
        raise ValueError("peg and thresholds must be finite")
    if peg <= 0:
        raise ValueError("peg must be positive")
    if warn_threshold < 0 or critical_threshold < 0:
        raise ValueError("thresholds must be non-negative")
    if critical_threshold < warn_threshold:
        raise ValueError("critical_threshold must be greater than or equal to warn_threshold")


def classify_price(
    price: float,
    *,
    peg: float,
    warn_threshold: float,
    critical_threshold: float,
) -> AlertLevel | None:
    """Return the alert level for a price or None when it is in range."""
    validate_thresholds(peg, warn_threshold, critical_threshold)
    if not math.isfinite(price) or price <= 0:
        raise ValueError("price must be finite and positive")

    deviation = abs(price - peg) / peg
    if deviation >= critical_threshold:
        return AlertLevel.CRITICAL
    if deviation >= warn_threshold:
        return AlertLevel.WARN
    return None


def median_price(readings: Mapping[str, float] | Iterable[tuple[str, float]]) -> float | None:
    """Return the deterministic median of finite positive source readings."""
    items = readings.items() if isinstance(readings, Mapping) else readings
    clean = []

    for source, value in items:
        try:
            price = float(value)
        except (TypeError, ValueError):
            continue
        if str(source).strip() and math.isfinite(price) and price > 0:
            clean.append(price)

    if not clean:
        return None

    return float(statistics.median(sorted(clean)))
