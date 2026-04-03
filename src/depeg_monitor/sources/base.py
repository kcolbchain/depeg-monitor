"""Abstract base class for price sources."""
from abc import ABC, abstractmethod


class PriceSource(ABC):
    """Fetches the current USD price of a stablecoin."""

    @abstractmethod
    async def get_price(self, symbol: str) -> float | None:
        """Return the current price or None if unavailable."""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        ...
