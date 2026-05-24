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

    def supports(self, symbol: str) -> bool:
        """Whether this source can theoretically price ``symbol``.

        Default returns True; concrete sources should override based on their
        symbol mapping so the monitor can log a real coverage matrix at startup
        instead of silently no-op'ing on unsupported pairs.
        """
        return True
