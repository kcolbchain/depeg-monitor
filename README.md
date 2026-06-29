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
adjustable warn / critical thresholds (same threshold semantics as this library's
`config/default.yaml`). See [`web/README.md`](web/README.md) for details.

## Features

- **Multi-source**: Uniswap V3 TWAP, Curve pool prices, Binance/Coinbase spot APIs
- **Consensus pegging**: aggregate every source into one consensus peg per cycle with a cross-venue agreement score and a watch/warning/critical severity model (see below)
- **Configurable thresholds**: Warning at 0.5%, critical at 1%, custom per-stablecoin
- **Multiple alert channels**: Console, Discord webhook, Slack webhook, generic HTTP
- **Structured alert feed**: pluggable sinks (stdout + webhook) that emit self-describing depeg events
- **Async**: Built on asyncio + aiohttp for high-throughput monitoring
- **Extensible**: Add new price sources, alert channels, or feed sinks by implementing a base class

## Consensus pegging & alert feed

Instead of firing one alert per source, consensus mode combines all venue
readings for a coin into a single, robust verdict each cycle:

1. **Consensus price** — the median of the per-source prices. With 3+ venues,
   gross outliers (a single broken/mispricing venue) are trimmed before the
   median is taken, so one bad feed can't move the peg.
2. **Agreement score** (`0..1`) — how tightly the venues cluster, derived from
   the min/max price spread (a 1% spread → 0), with a single uncorroborated
   source capped at `0.5`.
3. **Severity** — `normal` < `watch` < `warning` < `critical`, driven by the
   deviation from peg in basis points. Low agreement (venues disagreeing) bumps
   severity up one notch (capped at `warning`), because cross-venue divergence
   is itself an early depeg signal.

Matching depeg events are emitted as structured records (schema
`depeg-monitor/consensus-event/v1`) to every configured **sink**. Two ship
in-box — `StdoutSink` (logs, optionally as JSON) and `WebhookSink`
(generic/Slack/Discord) — and new transports just implement the `Sink`
interface. Enable it under the `consensus:` config block (`enabled: true`).

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

# Optional: multi-source consensus pegging + structured alert feed.
consensus:
  enabled: false
  watch_bps: 25.0        # severity tiers, in basis points of deviation
  warning_bps: 50.0
  critical_bps: 100.0
  min_agreement: 0.5     # below this, venues "disagree" → bump severity
  min_emit_severity: watch   # watch | warning | critical
  stdout_sink: true
  stdout_json: false
  webhook_url: ""
  webhook_platform: generic  # generic | slack | discord

interval_seconds: 30
```

## License

MIT
