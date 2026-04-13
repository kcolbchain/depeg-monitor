# depeg-monitor web dashboard

A zero-build, single-file browser dashboard showing live USDC / USDT / DAI
prices across three public sources, with the same warn/critical threshold
semantics as the Python library.

## Run locally

```bash
python3 -m http.server -d web 8080
# open http://localhost:8080
```

## Controls

- **Warn threshold** (bps) — default 50 (matches `warn_threshold: 0.005`).
- **Critical threshold** (bps) — default 100 (matches `critical_threshold: 0.01`).
- **Refresh** (s) — default 30 (matches `interval_seconds: 30`).

Changing thresholds re-renders without a refetch. Changing the interval
restarts the poll loop.

## Sources

| Source      | Endpoint                                               | Notes                                                                        |
| ----------- | ------------------------------------------------------ | ---------------------------------------------------------------------------- |
| Binance     | `api.binance.com/api/v3/ticker/price`                  | USDC/USDT, DAI/USDT spot. USDT itself pinned to 1 (USDT-quoted venue).       |
| Coinbase    | `api.coinbase.com/v2/exchange-rates?currency=USD`      | All three via the USD exchange-rate map; inverted to USD-per-coin.           |
| CoinGecko   | `api.coingecko.com/api/v3/simple/price`                | Volume-weighted proxy for DEX prices — cheaper than running a node.          |

The aggregated price shown on each card is the **median** of available
sources, matching the library's median-with-fallback behaviour.

## Deploy

Static files. Ships unchanged to GitHub Pages, Cloudflare Pages, or any
static host. No API keys required.

## Scope

This dashboard is a browser-side preview. The full
[depeg-monitor](https://github.com/kcolbchain/depeg-monitor) library runs
server-side with direct Uniswap V3 TWAP and Curve pool reads plus
Discord / Slack / HTTP alert channels.
