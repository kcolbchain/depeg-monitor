# depeg-monitor web dashboard

A zero-build, single-file browser dashboard for the top stablecoins, with both
live and historical views, peak-depeg event detection, and the
[kcolbchain brand](https://github.com/kcolbchain/brand) applied throughout.

## Run locally

```bash
python3 -m http.server -d web 8080
# open http://localhost:8080
```

## What's on the page

| Section | What it shows |
|---|---|
| **controls** | Coin list (comma-separated), warn/critical thresholds (bps), refresh interval (s), and the live / 1d / 7d / 30d / 90d / 1y mode toggle. |
| **peg deviation** | The headline chart — one line per tracked coin, centred on the configured peg, with warn and critical guide bands. Mode determines whether it's last-N live ticks or historical. |
| **notable events** | After loading any historical window, the table lists the top peg breaches where deviation stayed above the critical threshold. Ranked by peak deviation; click `view →` to highlight that coin's series in the chart. |
| **coins** | Per-coin metric cards with mini-sparklines and source breakdown (Binance / Coinbase / CoinGecko). |
| **alert log** | Severity transitions, history loads, focus jumps. |

## Coverage

20 stablecoins ship in the default coin list:
`USDC, USDT, DAI, FDUSD, PYUSD, USDe, FRAX, crvUSD, GHO, LUSD, TUSD, USDP, GUSD, USDD, sUSD, RLUSD, USDS, USD0, sDAI, agEUR`

Drop or add to the textarea in the controls section. Any symbol present in
`COIN_REGISTRY` (top of the `<script>` block in `index.html`) is supported;
add a new entry there to extend the registry.

## Data sources

| Mode | Source | Granularity |
|---|---|---|
| Live | Binance `/api/v3/ticker/price`, Coinbase `/v2/prices/:pair/spot`, CoinGecko `/api/v3/simple/price` | 1–60s polling (default 5s); median across whichever sources have a pair for that coin |
| 1d   | CoinGecko `/api/v3/coins/{id}/market_chart?days=1`   | 5-minute |
| 7d, 30d, 90d | CoinGecko `/api/v3/coins/{id}/market_chart?days=N` | hourly |
| 1y   | CoinGecko `/api/v3/coins/{id}/market_chart?days=365` | daily |

Historical loads are throttled at 350ms between coins to stay under CoinGecko's
free-tier rate limit. For >20 coins or sub-5s live polling, plug in a
paid CoinGecko key or your own backend.

## Brand

Visuals consume tokens from
[kcolbchain/brand](https://github.com/kcolbchain/brand). The local
[`tokens.css`](tokens.css) is a synced copy; refresh it from upstream rather
than editing values in place. Component patterns (chip, card, chart, table,
log) are documented at
[`brand/pages/`](https://github.com/kcolbchain/brand/tree/main/pages).

## What's not here yet

Tracked as follow-ups; the page calls these out only to remind us we haven't
forgotten:

- **Solana DEX prices** (Jupiter aggregator) and other non-Ethereum chains.
- **WebSocket streaming** (Binance / Coinbase have public WS feeds — would
  replace the 5s polling for sub-second updates without burning rate limits).
- **Custom non-stable assets** (e.g. XRP at a user-set target). Possible via
  `COIN_REGISTRY` already, but no UI for entering a non-1.0 peg.
- **Chart time-scrubbing** (click and drag across the historical chart to zoom
  into a depeg window). Today the `view →` jump-link only highlights a series.
