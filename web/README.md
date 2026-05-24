# depeg-monitor web dashboard

A zero-build browser dashboard for the top stablecoins, with live + historical
views, per-card analytics charts, an indicator library, a local-compute
sandbox, and the [depeg-oracles](../docs/DEPEG_ORACLES.md) wire format
exposed on `window`.

## Run locally

```bash
python3 -m http.server -d web 8080
# open http://localhost:8080
```

## What's on the page

| Section | What it shows |
|---|---|
| **header** | Wordmark + per-source status chips (`binance` / `coinbase` / `coingecko`) showing freshness and any rate-limit backoff. |
| **controls** | Coin list, warn/critical (bps), refresh interval (s), `live / 1d / 7d / 30d / 90d / 1y` mode, `individual / joint` view. |
| **indicators** | Checkbox row of pre-built overlays (EWMA, Bollinger upper/lower, volatility, drawdown, cross-source divergence). Toggle anytime. |
| **joint chart** *(joint view)* | Big multi-coin SVG time series. |
| **coins** | Per-coin cards. In `individual` view each card has its own full chart with active indicators overlaid; in `joint` view the per-card chart hides and the joint chart takes the stage. |
| **sandbox** | Paste your own `indicator(series, peg, perSource, i)` function, hit run, and it overlays on every card. Sample gallery in the dropdown. |
| **notable events** | After any historical load, ranked list of windows where deviation stayed above critical. |
| **alert log** | Severity transitions, source rate-limits, sandbox compile errors, history loads. |

## Coverage

20 stablecoins ship in the default coin list. Edit the textarea to add or
remove. New symbols are added by appending an entry to `COIN_REGISTRY` at the
top of the `<script>` block in `index.html`:

```js
NEW: { id: 'coingecko-id', peg: 1.0, binance: 'NEWUSDT', coinbase: null, color: '#hex' },
```

## Polling model

Each source has its own timer so a slow or rate-limited venue doesn't slow
the others:

| Source | Default interval | Notes |
|---|---|---|
| Binance     | 5s (= refresh) | Single batched request for every coin with a Binance pair |
| Coinbase    | 5s (= refresh) | One request per coin (Coinbase has no batch endpoint) |
| CoinGecko   | max(20s, refresh) | Free-tier rate-limited (30 calls/min). On HTTP 429 the source backs off 60s and the chip turns red |

The card price is the median of whichever sources are *fresh* (responded in
the last 60s). If CoinGecko is on cooldown, the median falls back to
Binance + Coinbase automatically; the missing source shows as `—` in the
per-source breakdown.

## Indicator library

Implemented in [`indicators.js`](indicators.js), exposed on
`window.depegIndicators`:

| Function | What it returns |
|---|---|
| `bps(price, peg)` | Single bps deviation |
| `asBps(series, peg)` | Convert price-domain series to bps-domain |
| `ewma(series, {alpha})` | Exponentially weighted MA (price domain) |
| `rolling(series, win, fn)` | Generic rolling-window reducer |
| `zscore(series, {peg, win})` | Rolling z-score of bps deviation |
| `volatility(series, {win})` | Rolling stddev of returns (bps) |
| `drawdown(series, {peg, eps})` | Worst |bps| since last full re-peg |
| `bollinger(series, {peg, win, k})` | `{upper, lower, mean}` bands |
| `recoveryTime(series, {peg, threshold, eps, coolDownTicks})` | Event list with durations |
| `sourceDivergence(perSourceSeries, {peg})` | Max-min bps across sources at each tick |

## Sandbox

The sandbox runs user-supplied JavaScript in a `new Function()` wrapper —
sandboxed in the sense that it can't reach outside your tab; **not**
sandboxed in the sense that it could spin a loop and freeze your tab. Treat
it like a browser dev-tools snippet: it's running on your own machine, in
your own session, with your own permissions.

Signature: `indicator(series, peg, perSource, i) → [{t, value}]`.

* `series` — the current coin's series, oldest first.
* `peg` — the configured peg (e.g. 1.0).
* `perSource` — `{ binance: [{t, price}], coinbase: [...], coingecko: [...] }` for that coin.
* `i` — the full indicators module (`i.ewma`, `i.zscore`, `i.bps`, …).

Return value is plotted as an overlay on every coin card. Compile errors
show in the alert log; runtime errors per coin show the same.

## Power-user surface

`window.depegMonitor` exposes the live state for browser-extension /
copy-paste use:

```js
window.depegMonitor.lastObservations   // [{ schema, ts, coin, median_price, ... }]
window.depegMonitor.registry           // COIN_REGISTRY
window.depegMonitor.indicators         // same as window.depegIndicators
window.depegMonitor.state              // raw history buffers
```

`lastObservations` is the in-browser implementation of the
[depeg-oracles observation schema](../docs/DEPEG_ORACLES.md). It's
unsigned (browsers shouldn't hold long-lived keys); a server-side observer
that wraps the same data with a signature is described in the spec.

## What's not here yet

Tracked as follow-ups:

- **Solana / non-Ethereum DEX** prices (Jupiter aggregator).
- **WebSocket streaming** via Binance/Coinbase public feeds.
- **Custom non-stable peg targets** (UI for entering peg per row).
- **Drag-to-zoom** on the historical chart.
- **Observer signing + JSONL output** — the dashboard would write
  signed observations to the File System Access API.
