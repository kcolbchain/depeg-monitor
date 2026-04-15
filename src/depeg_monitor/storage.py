"""SQLite storage for historical depeg event logging."""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Optional

from .alerts.base import AlertLevel


class Severity(Enum):
    """Stored severity levels (maps from AlertLevel)."""
    WARN = "warn"
    CRITICAL = "critical"


@dataclass
class DepegEvent:
    """A single recorded depeg event."""
    id: Optional[int] = None
    timestamp: float = 0.0
    stablecoin: str = ""
    source: str = ""
    price: float = 0.0
    peg: float = 1.0
    deviation: float = 0.0
    severity: str = "warn"


class DepegDatabase:
    """SQLite-backed storage for depeg events."""

    def __init__(self, db_path: str = "depeg_events.db"):
        self.db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()

    def _init_db(self) -> None:
        """Create the events table if it doesn't exist."""
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS depeg_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                stablecoin TEXT NOT NULL,
                source TEXT NOT NULL,
                price REAL NOT NULL,
                peg REAL NOT NULL,
                deviation REAL NOT NULL,
                severity TEXT NOT NULL
            )
        """)
        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_depeg_stablecoin
            ON depeg_events(stablecoin)
        """)
        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_depeg_timestamp
            ON depeg_events(timestamp DESC)
        """)
        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_depeg_severity
            ON depeg_events(severity)
        """)
        self.conn.commit()

    @property
    def conn(self) -> sqlite3.Connection:
        """Lazy connection — opens on first access."""
        if self._conn is None:
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self.db_path)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def log_event(
        self,
        stablecoin: str,
        source: str,
        price: float,
        peg: float,
        deviation: float,
        level: AlertLevel,
    ) -> DepegEvent:
        """Insert a new depeg event and return it."""
        now = time.time()
        severity = level.value
        cur = self.conn.execute(
            """INSERT INTO depeg_events
               (timestamp, stablecoin, source, price, peg, deviation, severity)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (now, stablecoin, source, price, peg, deviation, severity),
        )
        self.conn.commit()
        return DepegEvent(
            id=cur.lastrowid,
            timestamp=now,
            stablecoin=stablecoin,
            source=source,
            price=price,
            peg=peg,
            deviation=deviation,
            severity=severity,
        )

    def query_history(
        self,
        stablecoin: Optional[str] = None,
        severity: Optional[str] = None,
        hours: int = 24,
        limit: int = 50,
    ) -> list[DepegEvent]:
        """Query historical depeg events.

        Args:
            stablecoin: Filter by symbol (e.g. "USDC"). None = all.
            severity: Filter by severity ("warn" or "critical"). None = all.
            hours: Look back this many hours.
            limit: Max rows to return.
        """
        since = time.time() - hours * 3600
        clauses = ["timestamp >= ?"]
        params: list = [since]

        if stablecoin:
            clauses.append("stablecoin = ?")
            params.append(stablecoin)
        if severity:
            clauses.append("severity = ?")
            params.append(severity)

        where = " AND ".join(clauses)
        params.append(limit)

        rows = self.conn.execute(
            f"SELECT * FROM depeg_events WHERE {where} ORDER BY timestamp DESC LIMIT ?",
            params,
        ).fetchall()

        return [
            DepegEvent(
                id=r["id"],
                timestamp=r["timestamp"],
                stablecoin=r["stablecoin"],
                source=r["source"],
                price=r["price"],
                peg=r["peg"],
                deviation=r["deviation"],
                severity=r["severity"],
            )
            for r in rows
        ]

    def get_stats(self, hours: int = 24) -> dict:
        """Get summary statistics for the time window."""
        since = time.time() - hours * 3600
        row = self.conn.execute(
            """SELECT
                   COUNT(*) as total_events,
                   COUNT(CASE WHEN severity = 'critical' THEN 1 END) as critical_count,
                   COUNT(CASE WHEN severity = 'warn' THEN 1 END) as warn_count,
                   COUNT(DISTINCT stablecoin) as coins_affected,
                   MAX(deviation) as max_deviation,
                   AVG(deviation) as avg_deviation
               FROM depeg_events
               WHERE timestamp >= ?""",
            (since,),
        ).fetchone()
        return {
            "period_hours": hours,
            "total_events": row["total_events"],
            "critical_events": row["critical_count"],
            "warn_events": row["warn_count"],
            "coins_affected": row["coins_affected"],
            "max_deviation": round(row["max_deviation"], 6) if row["max_deviation"] else 0,
            "avg_deviation": round(row["avg_deviation"], 6) if row["avg_deviation"] else 0,
        }

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None
