"""CLI entry point with history subcommand."""
import asyncio
import logging
import sys
import yaml
from datetime import datetime
from pathlib import Path
from .config import MonitorConfig
from .monitor import DepegMonitor
from .storage import DepegDatabase


def _load_config(config_path: str) -> MonitorConfig:
    """Load configuration from YAML file."""
    path = Path(config_path)
    if path.exists():
        with open(path) as f:
            raw = yaml.safe_load(f)
        return MonitorConfig(**raw) if raw else MonitorConfig()
    logging.info(f"Config {config_path} not found, using defaults")
    return MonitorConfig()


def cmd_history(args: list[str]) -> None:
    """Query and display historical depeg events."""
    db_path = "depeg_events.db"
    stablecoin = None
    severity = None
    hours = 24
    limit = 50
    show_stats = False

    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ("--db", "-d") and i + 1 < len(args):
            db_path = args[i + 1]
            i += 2
        elif arg in ("--coin", "-c") and i + 1 < len(args):
            stablecoin = args[i + 1].upper()
            i += 2
        elif arg in ("--severity", "-s") and i + 1 < len(args):
            severity = args[i + 1].lower()
            i += 2
        elif arg in ("--hours", "-H") and i + 1 < len(args):
            hours = int(args[i + 1])
            i += 2
        elif arg in ("--limit", "-l") and i + 1 < len(args):
            limit = int(args[i + 1])
            i += 2
        elif arg == "--stats":
            show_stats = True
            i += 1
        else:
            i += 1

    db = DepegDatabase(db_path)

    if show_stats:
        stats = db.get_stats(hours=hours)
        print(f"\n📊 Depeg Monitor — Last {stats['period_hours']}h Summary")
        print(f"{'=' * 50}")
        print(f"  Total events:    {stats['total_events']}")
        print(f"  Critical:        {stats['critical_events']}")
        print(f"  Warnings:        {stats['warn_events']}")
        print(f"  Coins affected:  {stats['coins_affected']}")
        print(f"  Max deviation:   {stats['max_deviation']:.4%}")
        print(f"  Avg deviation:   {stats['avg_deviation']:.4%}")
        db.close()
        return

    events = db.query_history(
        stablecoin=stablecoin,
        severity=severity,
        hours=hours,
        limit=limit,
    )

    if not events:
        print(f"No depeg events found in the last {hours}h.")
        if stablecoin:
            print(f"  (filtered by coin: {stablecoin})")
        db.close()
        return

    header = f"📋 Depeg Events — Last {hours}h"
    if stablecoin:
        header += f" ({stablecoin})"
    print(f"\n{header}")
    print(f"{'=' * 80}")
    print(f"{'Time':<21} {'Coin':<6} {'Source':<12} {'Price':<10} {'Deviation':<12} {'Severity'}")
    print(f"{'-' * 80}")

    for ev in events:
        ts = datetime.fromtimestamp(ev.timestamp).strftime("%Y-%m-%d %H:%M:%S")
        dev_str = f"{ev.deviation:.4%}"
        sev = "🔴 CRITICAL" if ev.severity == "critical" else "🟡 WARN"
        print(f"{ts:<21} {ev.stablecoin:<6} {ev.source:<12} {ev.price:<10.6f} {dev_str:<12} {sev}")

    print(f"{'-' * 80}")
    print(f"Showing {len(events)} events (limit: {limit})")
    db.close()


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(message)s",
        datefmt="%H:%M:%S",
    )

    # Subcommand routing
    if len(sys.argv) > 1 and sys.argv[1] == "history":
        cmd_history(sys.argv[2:])
        return

    config_path = "config/default.yaml"
    for i, arg in enumerate(sys.argv):
        if arg == "--config" and i + 1 < len(sys.argv):
            config_path = sys.argv[i + 1]

    config = _load_config(config_path)
    monitor = DepegMonitor(config)
    asyncio.run(monitor.run())


if __name__ == "__main__":
    main()
