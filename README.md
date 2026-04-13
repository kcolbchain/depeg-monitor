# depeg-monitor

Real-time stablecoin depeg detection and alerting. By [kcolbchain](https://kcolbchain.com) (est. 2015).

## Why this exists

Stablecoin depegs can cascade into billions in losses within hours (USDC/SVB 2023, UST 2022). Existing monitoring tools are either proprietary or delayed. This tool watches USDT/USDC/DAI across DEXes and CEXes in real-time and fires alerts the moment price deviates beyond your threshold.

Built on findings from the BIS and NBER stablecoin run-risk research (2025).

## Quick start

```bash
pip install -e .
depeg-monitor --config config/default.yaml
```

## Live dashboard

A zero-build static dashboard lives in [`web/`](web/). Run it locally with
`python3 -m http.server -d web 8080` — it polls Binance, Coinbase, and
CoinGecko every 30s and renders median-aggregated peg status with
adjustable warn / critical thresholds (same bps semantics as this library's
`config/default.yaml`). See [`web/README.md`](web/README.md) for details.

## Features

- **Multi-source**: Uniswap V3 TWAP, Curve pool prices, Binance/Coinbase spot APIs
- **Configurable thresholds**: Warning at 0.5%, critical at 1%, custom per-stablecoin
- **Multiple alert channels**: Console, Discord webhook, Slack webhook, generic HTTP
- **Async**: Built on asyncio + aiohttp for high-throughput monitoring
- **Extensible**: Add new price sources or alert channels by implementing a base class

## Architecture

```
Sources (DEX + CEX)
    ↓ async fetch
Monitor loop (configurable interval)
    ↓ compare against thresholds
Alert dispatcher
    ↓ fan-out
Console / Discord / Slack / Webhook
```

## Config

```yaml
stablecoins:
  - symbol: USDC
    peg: 1.0
    warn_threshold: 0.005    # 0.5%
    critical_threshold: 0.01  # 1.0%
  - symbol: USDT
    peg: 1.0
    warn_threshold: 0.005
    critical_threshold: 0.01

sources:
  cex:
    - binance
    - coinbase
  dex:
    rpc_url: "https://eth.llamarpc.com"

alerts:
  console: true
  discord_webhook: ""  # optional
  slack_webhook: ""    # optional

interval_seconds: 30
```

## License

MIT
