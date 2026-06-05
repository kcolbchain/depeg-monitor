# DEPEG-MONITOR — Patty's Overview

_Last updated: 2026-04-17_

---

## What it does

Real-time stablecoin depeg detection and alerting for USDC, USDT, and DAI.
Runs a configurable polling loop (default 30 s), pulls prices from multiple
sources, compares against per-coin thresholds, and fans out alerts to any
combination of Console, Discord webhook, Slack webhook, and Telegram.

### Entry point

```
pip install -e .
depeg-monitor --config config/default.yaml
```

CLI defined in `src/depeg_monitor/cli.py:main()`.

---

## Architecture

```
config/default.yaml
    └─ MonitorConfig (pydantic)
            │
            ▼
       DepegMonitor (monitor.py)
        ├─ Sources (every tick, per coin)
        │   ├─ BinanceSource   — Binance REST /api/v3/ticker/price
        │   ├─ CoinbaseSource  — Coinbase /v2/prices/{pair}/spot
        │   └─ UniswapV3Source — Ethereum RPC slot0() → sqrtPriceX96
        │
        └─ Alerts (fan-out on threshold breach)
            ├─ ConsoleAlert   — logging.warning / logging.critical
            ├─ WebhookAlert   — Discord or Slack HTTP POST
            └─ TelegramAlert  — Telegram Bot API sendMessage
```

### Thresholds (default)

| Level    | Deviation |
|----------|-----------|
| WARN     | ≥ 0.5 %   |
| CRITICAL | ≥ 1.0 %   |

Per-coin overrides supported in YAML.

### Web dashboard

Zero-build static page at `web/index.html`. Run with
`python3 -m http.server -d web 8080`. Polls Binance, Coinbase, CoinGecko
every 30 s in-browser, renders median-aggregated price, sparkline history,
and an alert log. Thresholds are adjustable live via number inputs.

---

## Issues

### CRITICAL

**1. DEX source returns a meaningless price (always triggers CRITICAL)**
`src/depeg_monitor/sources/dex.py:48–54`

`sqrtPriceX96` from Uniswap V3 slot0 gives the stablecoin/WETH ratio. The
code returns `1.0 / price` without multiplying by the current ETH/USD price.
When ETH ≈ $3000, the returned "price" for USDC is ≈ 0.00033 — a ~99.97 %
depeg. Every single monitoring cycle will fire CRITICAL alerts for all three
coins via the Uniswap source. The DEX source is non-functional in its current
state; it needs an ETH/USD oracle feed (e.g. Chainlink, or a separate Binance
ETH/USDT fetch) before the result can be used.

**2. No alert deduplication / state tracking**
`src/depeg_monitor/monitor.py:57–70`

There is no memory of previous alert state. Every 30-second tick fires fresh
alerts for each source independently. During a real depeg, three sources ×
N coins = multiple alerts per tick, continuously for the duration of the
event. Over an hour at 30 s interval that is 720 alerts. Channels like
Telegram will rate-limit (HTTP 429); Discord and Slack will treat it as spam.
Need stateful tracking: fire once on depeg entry, suppress until recovery,
then fire a "re-pegged" notification.

### HIGH

**3. DEX call blocks the event loop**
`src/depeg_monitor/sources/dex.py:43–46`

`pool.functions.slot0().call()` is a synchronous blocking web3.py call inside
`async def get_price()`. This stalls the entire asyncio event loop while
waiting for the Ethereum RPC response (typically 100–500 ms per call). With
3 coins that is 300–1500 ms of blocking per tick. Fix: wrap in
`asyncio.get_event_loop().run_in_executor(None, ...)` or switch to web3.py's
async provider.

**4. Missing CLI entry point in pyproject.toml**
`pyproject.toml`

The README instructs `depeg-monitor --config ...` but there is no
`[project.scripts]` section in `pyproject.toml`. After `pip install -e .`
the command does not exist. Fix:

```toml
[project.scripts]
depeg-monitor = "depeg_monitor.cli:main"
```

### MEDIUM

**5. Per-call aiohttp.ClientSession (BinanceSource, CoinbaseSource, WebhookAlert)**
`src/depeg_monitor/sources/cex.py:19`, `src/depeg_monitor/alerts/webhook.py:22`

A new `aiohttp.ClientSession` is created and torn down on every single
`get_price()` / `send()` call. Sessions are designed to be reused across
requests; creating one per call wastes TCP connection setup and generates
deprecation warnings in recent aiohttp versions. Each source/alert should
hold a shared session (like TelegramAlert already does).

**6. TelegramAlert session is never closed**
`src/depeg_monitor/alerts/telegram.py:133–142`

`TelegramAlert` owns an `aiohttp.ClientSession` that is only closed via
`async with` / `__aexit__`. `DepegMonitor` never calls `close()` on any of
its alert objects, so the session leaks on shutdown (ResourceWarning at
exit). `DepegMonitor.run()` or a new `shutdown()` method should close all
alert objects that support it.

**7. Binance USDT pricing is an indirect proxy**
`src/depeg_monitor/sources/cex.py:6, 26–27`

`BINANCE_PAIRS` maps USDT to "USDCUSDT" and inverts the price:
`USDT_price ≈ 1 / (USDC/USDT rate)`. This conflates a USDC depeg with
USDT's price. If USDC depegs to $0.97 while USDT holds at $1.00, Binance
will report USDT = $1.031 — a false USDT depeg alert. Use a stablecoin/fiat
pair (e.g. USDT/BUSD, or derive from USDT/BTC + BTC/USD) or accept the
limitation and document it.

### LOW

**8. pytest-asyncio not in requirements.txt**
`requirements.txt`

Tests use `@pytest.mark.asyncio` and `asyncio_mode = auto` (pytest.ini), but
`pytest-asyncio` is not listed as a dependency. Running `pip install -r
requirements.txt && pytest` will fail. Add `pytest-asyncio>=0.23.0` to
requirements.txt (or a separate `requirements-dev.txt`).

**9. Telegram not documented in default config**
`config/default.yaml`

The Telegram alert channel was added in PR #10 but `config/default.yaml` has
no commented-out `telegram_bot_token` / `telegram_chat_id` fields. Users
reading only the config file won't know Telegram is available. Add commented
example lines.

---

## Module map

| File | Purpose |
|------|---------|
| `src/depeg_monitor/cli.py` | Argument parsing, config loading, `asyncio.run(monitor.run())` |
| `src/depeg_monitor/config.py` | Pydantic models for YAML config |
| `src/depeg_monitor/monitor.py` | Core loop: check_once(), _check_coin(), run() |
| `src/depeg_monitor/sources/base.py` | `PriceSource` ABC |
| `src/depeg_monitor/sources/cex.py` | Binance + Coinbase REST |
| `src/depeg_monitor/sources/dex.py` | Uniswap V3 slot0 via web3.py |
| `src/depeg_monitor/alerts/base.py` | `Alert` ABC + `AlertLevel` enum |
| `src/depeg_monitor/alerts/console.py` | stdlib logging |
| `src/depeg_monitor/alerts/webhook.py` | Discord / Slack / generic HTTP POST |
| `src/depeg_monitor/alerts/telegram.py` | Telegram Bot API |
| `config/default.yaml` | Default config (USDC/USDT/DAI, Binance+Coinbase+Uniswap) |
| `web/index.html` | Browser-only live dashboard (no server needed) |
| `tests/test_integration.py` | Mock-source integration tests for alert thresholds |
| `tests/test_telegram_alert.py` | Unit tests for TelegramAlert formatting + HTTP handling |

---

## Git history (summary)

| Commit | What |
|--------|------|
| `721eecd` | Initial scaffold |
| `76ad3f5` | CONTRIBUTING.md |
| `8d00d43` / `11e62a0` | Integration tests (issue #4) |
| `556991a` | CONTRIBUTORS.md |
| `c27144d` | Web dashboard (PR #8) |
| `f6f1e64` / `40906e9` | Telegram alert channel (PR #10, external contributor) |
