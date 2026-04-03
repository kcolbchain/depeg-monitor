"""Abstract base class for alert channels."""
from abc import ABC, abstractmethod
from enum import Enum


class AlertLevel(Enum):
    INFO = "info"
    WARN = "warn"
    CRITICAL = "critical"


class Alert(ABC):
    @abstractmethod
    async def send(self, level: AlertLevel, symbol: str, price: float, peg: float, source: str) -> None:
        ...
