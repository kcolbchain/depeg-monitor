"""Database alert — logs depeg events to SQLite for historical querying."""

from .alerts.base import Alert, AlertLevel
from .storage import DepegDatabase


class DatabaseAlert(Alert):
    """Persists every depeg event to SQLite storage.

    This is not a traditional "alert" — it records events so they can be
    queried later via ``depeg-monitor history``.
    """

    def __init__(self, db_path: str = "depeg_events.db"):
        self.db = DepegDatabase(db_path)

    async def send(
        self, level: AlertLevel, symbol: str, price: float, peg: float, source: str
    ) -> None:
        deviation = abs(price - peg) / peg
        self.db.log_event(
            stablecoin=symbol,
            source=source,
            price=price,
            peg=peg,
            deviation=deviation,
            level=level,
        )

    def close(self) -> None:
        self.db.close()
