"""Configuration model using pydantic."""

from __future__ import annotations

import math
from typing import Optional

from pydantic import BaseModel, field_validator, model_validator


class StablecoinConfig(BaseModel):
    symbol: str
    peg: float = 1.0
    warn_threshold: float = 0.005
    critical_threshold: float = 0.01

    @field_validator("peg", "warn_threshold", "critical_threshold")
    @classmethod
    def values_must_be_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("threshold and peg values must be finite")
        return value

    @model_validator(mode="after")
    def thresholds_must_be_ordered(self) -> "StablecoinConfig":
        if self.peg <= 0:
            raise ValueError("peg must be positive")
        if self.warn_threshold < 0:
            raise ValueError("warn_threshold must be non-negative")
        if self.critical_threshold < 0:
            raise ValueError("critical_threshold must be non-negative")
        if self.critical_threshold < self.warn_threshold:
            raise ValueError("critical_threshold must be greater than or equal to warn_threshold")
        return self


class DexSourceConfig(BaseModel):
    rpc_url: str = "https://eth.llamarpc.com"


class SourcesConfig(BaseModel):
    cex: list[str] = ["binance", "coinbase"]
    dex: DexSourceConfig = DexSourceConfig()


class AlertsConfig(BaseModel):
    console: bool = True
    discord_webhook: Optional[str] = None
    slack_webhook: Optional[str] = None
    # Telegram alert configuration
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    # SQLite event logging — opt-in; set a path to enable
    db_path: Optional[str] = None


class ConsensusFeedConfig(BaseModel):
    """Configuration for the multi-source consensus alert feed.

    When ``enabled``, the monitor aggregates every source's reading for a coin
    into a single consensus peg per cycle and emits a structured depeg event to
    the configured sinks, instead of (or in addition to) one alert per source.
    """

    enabled: bool = False
    # Severity thresholds, in basis points of deviation from peg.
    watch_bps: float = 25.0
    warning_bps: float = 50.0
    critical_bps: float = 100.0
    # Agreement score (0..1) below which venues are treated as disagreeing,
    # escalating severity by one notch (capped at warning).
    min_agreement: float = 0.5
    # Only publish events at or above this severity:
    # one of "watch", "warning", "critical".
    min_emit_severity: str = "watch"
    # Sinks:
    stdout_sink: bool = True
    stdout_json: bool = False
    webhook_url: Optional[str] = None
    # "generic", "slack", or "discord" — shapes the webhook body.
    webhook_platform: str = "generic"

    @field_validator("watch_bps", "warning_bps", "critical_bps", "min_agreement")
    @classmethod
    def values_must_be_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("consensus feed numeric values must be finite")
        return value

    @model_validator(mode="after")
    def validate_ordering(self) -> "ConsensusFeedConfig":
        if not (self.watch_bps <= self.warning_bps <= self.critical_bps):
            raise ValueError("thresholds must satisfy watch_bps <= warning_bps <= critical_bps")
        if not (0.0 <= self.min_agreement <= 1.0):
            raise ValueError("min_agreement must be within [0, 1]")
        if self.min_emit_severity.lower() not in {"watch", "warning", "critical"}:
            raise ValueError("min_emit_severity must be one of watch/warning/critical")
        return self


class MonitorConfig(BaseModel):
    stablecoins: list[StablecoinConfig] = [
        StablecoinConfig(symbol="USDC"),
        StablecoinConfig(symbol="USDT"),
        StablecoinConfig(symbol="DAI"),
    ]
    sources: SourcesConfig = SourcesConfig()
    alerts: AlertsConfig = AlertsConfig()
    consensus: ConsensusFeedConfig = ConsensusFeedConfig()
    interval_seconds: int = 30

    @field_validator("interval_seconds")
    @classmethod
    def interval_must_be_positive(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("interval_seconds must be positive")
        return value
