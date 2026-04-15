"""Tests for SQLite depeg event storage."""

import os
import tempfile
import time
import pytest

from depeg_monitor.storage import DepegDatabase, DepegEvent
from depeg_monitor.alerts.base import AlertLevel
from depeg_monitor.database_alert import DatabaseAlert


@pytest.fixture
def db(tmp_path):
    """Create a temporary database."""
    path = str(tmp_path / "test.db")
    database = DepegDatabase(path)
    yield database
    database.close()


class TestDepegDatabase:
    def test_creates_tables(self, db):
        """Database should create tables on init."""
        tables = db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        names = [t["name"] for t in tables]
        assert "depeg_events" in names

    def test_log_and_retrieve_event(self, db):
        """Logging an event and querying it should work."""
        event = db.log_event(
            stablecoin="USDC",
            source="binance",
            price=0.985,
            peg=1.0,
            deviation=0.015,
            level=AlertLevel.CRITICAL,
        )
        assert event.id is not None
        assert event.stablecoin == "USDC"
        assert event.severity == "critical"

        events = db.query_history()
        assert len(events) == 1
        assert events[0].stablecoin == "USDC"

    def test_query_filters_by_stablecoin(self, db):
        """Query should filter by stablecoin."""
        db.log_event("USDC", "binance", 0.985, 1.0, 0.015, AlertLevel.WARN)
        db.log_event("USDT", "coinbase", 0.97, 1.0, 0.03, AlertLevel.CRITICAL)

        usdc = db.query_history(stablecoin="USDC")
        assert len(usdc) == 1
        assert usdc[0].stablecoin == "USDC"

        usdt = db.query_history(stablecoin="USDT")
        assert len(usdt) == 1

        all_events = db.query_history()
        assert len(all_events) == 2

    def test_query_filters_by_severity(self, db):
        """Query should filter by severity."""
        db.log_event("USDC", "binance", 0.985, 1.0, 0.015, AlertLevel.WARN)
        db.log_event("USDC", "coinbase", 0.97, 1.0, 0.03, AlertLevel.CRITICAL)

        critical = db.query_history(severity="critical")
        assert len(critical) == 1
        assert critical[0].severity == "critical"

        warn = db.query_history(severity="warn")
        assert len(warn) == 1

    def test_query_respects_limit(self, db):
        """Query should respect the limit parameter."""
        for i in range(10):
            db.log_event("USDC", "binance", 0.99 - i * 0.001, 1.0, 0.01 + i * 0.001, AlertLevel.WARN)

        events = db.query_history(limit=3)
        assert len(events) == 3

    def test_query_most_recent_first(self, db):
        """Events should be returned newest first."""
        db.log_event("USDC", "binance", 0.99, 1.0, 0.01, AlertLevel.WARN)
        time.sleep(0.01)
        db.log_event("USDT", "coinbase", 0.97, 1.0, 0.03, AlertLevel.CRITICAL)

        events = db.query_history()
        assert events[0].stablecoin == "USDT"  # more recent
        assert events[1].stablecoin == "USDC"

    def test_get_stats(self, db):
        """Stats should aggregate correctly."""
        db.log_event("USDC", "binance", 0.985, 1.0, 0.015, AlertLevel.WARN)
        db.log_event("USDT", "coinbase", 0.97, 1.0, 0.03, AlertLevel.CRITICAL)
        db.log_event("DAI", "binance", 0.96, 1.0, 0.04, AlertLevel.CRITICAL)

        stats = db.get_stats(hours=1)
        assert stats["total_events"] == 3
        assert stats["critical_events"] == 2
        assert stats["warn_events"] == 1
        assert stats["coins_affected"] == 3
        assert stats["max_deviation"] == 0.04
        assert stats["avg_deviation"] == pytest.approx(0.028333, abs=1e-4)

    def test_get_stats_empty(self, db):
        """Stats should return zeros when no events."""
        stats = db.get_stats(hours=1)
        assert stats["total_events"] == 0
        assert stats["critical_events"] == 0

    def test_close_and_reopen(self, tmp_path):
        """Database should persist across close/reopen."""
        path = str(tmp_path / "persist.db")
        db1 = DepegDatabase(path)
        db1.log_event("USDC", "binance", 0.99, 1.0, 0.01, AlertLevel.WARN)
        db1.close()

        db2 = DepegDatabase(path)
        events = db2.query_history()
        assert len(events) == 1
        assert events[0].stablecoin == "USDC"
        db2.close()

    def test_db_path_creates_parent_dirs(self, tmp_path):
        """Should create parent directories if they don't exist."""
        path = str(tmp_path / "nested" / "dir" / "test.db")
        db = DepegDatabase(path)
        db.log_event("USDC", "binance", 0.99, 1.0, 0.01, AlertLevel.WARN)
        events = db.query_history()
        assert len(events) == 1
        db.close()


class TestDatabaseAlert:
    @pytest.mark.asyncio
    async def test_send_logs_event(self, tmp_path):
        """DatabaseAlert.send() should persist an event."""
        path = str(tmp_path / "alert.db")
        alert = DatabaseAlert(path)

        await alert.send(AlertLevel.CRITICAL, "USDC", 0.985, 1.0, "binance")

        db = DepegDatabase(path)
        events = db.query_history()
        assert len(events) == 1
        assert events[0].stablecoin == "USDC"
        assert events[0].severity == "critical"
        assert events[0].deviation == pytest.approx(0.015)
        db.close()
        alert.close()

    @pytest.mark.asyncio
    async def test_send_computes_deviation(self, tmp_path):
        """DatabaseAlert should compute deviation from price and peg."""
        path = str(tmp_path / "dev.db")
        alert = DatabaseAlert(path)

        await alert.send(AlertLevel.WARN, "DAI", 0.992, 1.0, "uniswap")

        db = DepegDatabase(path)
        events = db.query_history()
        assert events[0].deviation == pytest.approx(0.008)
        db.close()
        alert.close()
