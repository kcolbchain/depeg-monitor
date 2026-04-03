"""Configuration model using pydantic."""
from __future__ import annotations
from pydantic import BaseModel
from typing import Optional


class StablecoinConfig(BaseModel):
    symbol: str
    peg: float = 1.0
    warn_threshold: float = 0.005
    critical_threshold: float = 0.01


class DexSourceConfig(BaseModel):
    rpc_url: str = "https://eth.llamarpc.com"


class SourcesConfig(BaseModel):
    cex: list[str] = ["binance", "coinbase"]
    dex: DexSourceConfig = DexSourceConfig()


class AlertsConfig(BaseModel):
    console: bool = True
    discord_webhook: Optional[str] = None
    slack_webhook: Optional[str] = None


class MonitorConfig(BaseModel):
    stablecoins: list[StablecoinConfig] = [
        StablecoinConfig(symbol="USDC"),
        StablecoinConfig(symbol="USDT"),
        StablecoinConfig(symbol="DAI"),
    ]
    sources: SourcesConfig = SourcesConfig()
    alerts: AlertsConfig = AlertsConfig()
    interval_seconds: int = 30
