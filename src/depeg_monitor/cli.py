"""CLI entry point."""
import asyncio
import logging
import sys
import yaml
from pathlib import Path
from .config import MonitorConfig
from .monitor import DepegMonitor


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(message)s",
        datefmt="%H:%M:%S",
    )

    config_path = "config/default.yaml"
    for i, arg in enumerate(sys.argv):
        if arg == "--config" and i + 1 < len(sys.argv):
            config_path = sys.argv[i + 1]

    path = Path(config_path)
    if path.exists():
        with open(path) as f:
            raw = yaml.safe_load(f)
        config = MonitorConfig(**raw) if raw else MonitorConfig()
    else:
        logging.info(f"Config {config_path} not found, using defaults")
        config = MonitorConfig()

    monitor = DepegMonitor(config)
    asyncio.run(monitor.run())


if __name__ == "__main__":
    main()
