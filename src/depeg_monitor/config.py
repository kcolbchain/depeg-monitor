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


class MonitorConfig(BaseModel):
    stablecoins: list[StablecoinConfig] = [
        StablecoinConfig(symbol="USDC"),
        StablecoinConfig(symbol="USDT"),
        StablecoinConfig(symbol="DAI"),
    ]
    sources: SourcesConfig = SourcesConfig()
    alerts: AlertsConfig = AlertsConfig()
    interval_seconds: int = 30

    @field_validator("interval_seconds")
    @classmethod
    def interval_must_be_positive(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("interval_seconds must be positive")
        return value
