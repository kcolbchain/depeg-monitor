# depeg-oracles

A specification for a peer network of independent observers that publish their
own depeg observations. The goal: trustless, replicable, **open** depeg
signal — an alternative to closed, paywalled stablecoin-risk dashboards.

> Status: draft 0.1. The wire format below is implemented by the
> `depeg-monitor` Python library and the in-browser dashboard ships an
> observer mode. The aggregation layer (multi-observer consensus, on-chain
> attestation) is sketched here but not yet implemented.

## Why

Today, "is USDC depegged?" is answered by:

1. **The exchange you're trading on**, which has every incentive to delay
   bad news that triggers withdrawals.
2. **A few closed risk dashboards** (Chaos Labs, Gauntlet, Llama Risk),
   which are excellent but proprietary, paywalled at the API layer, and
   present a single point of trust.
3. **Twitter screenshots**, which is the de-facto consensus mechanism for
   most of crypto and is exactly as bad as it sounds.

A depeg-oracle network replaces step 3 with something checkable. Anyone
running `depeg-monitor` becomes an observer. Observers publish their
observations in a common wire format. Aggregators (and end-users) compute
the median observation across N observers — a depeg call is "real" once a
quorum agrees, not when one venue twitches.

## The observer

An **observer** is any process that:

1. Polls one or more price sources (CEX, DEX, or oracle network).
2. Computes deviation against a published peg.
3. Emits observations in the wire format below.

The reference implementation is this repo. `depeg-monitor` produces
observations on every cycle; the SQLite `events.db` is the canonical local
log; the optional `--export` flag (TODO) writes a JSONL stream that any
consumer can tail.

Observers are not trusted — they're verified by other observers.
The point of running many is that no single venue or operator can lie
without being outvoted.

## The observation

A single observation looks like this:

```json
{
  "schema":         "depeg-oracle/observation/v1",
  "observer_id":    "did:web:example.com:obs-01",
  "observer_pubkey":"ed25519:Ab12...",
  "ts":             "2026-05-24T14:21:03.412Z",
  "coin":           "USDC",
  "peg":            1.0,
  "median_price":   0.9941,
  "deviation_bps":  -59.0,
  "severity":       "warn",
  "sources": [
    { "name": "binance",     "pair": "USDCUSDT",  "price": 0.9939, "ts": "2026-05-24T14:21:02.901Z" },
    { "name": "coinbase",    "pair": "USDC-USD",  "price": 0.9943, "ts": "2026-05-24T14:21:03.011Z" },
    { "name": "coingecko",   "pair": "usd-coin",  "price": 0.9941, "ts": "2026-05-24T14:21:00.000Z" },
    { "name": "uniswap_v3",  "pair": "0x88e6...", "price": 0.9942, "ts": "2026-05-24T14:21:03.107Z" }
  ],
  "config": {
    "warn_threshold_bps":     50,
    "critical_threshold_bps": 100,
    "aggregator":             "median"
  },
  "sig": "ed25519:base64..."
}
```

Field meanings:

| Field | Required | Notes |
|---|---|---|
| `schema` | yes | Wire-format version. Bump on breaking changes. |
| `observer_id` | yes | A DID, ENS name, or any URI. Used to deduplicate across observations and to look up `observer_pubkey`. |
| `observer_pubkey` | yes | The public key paired with `sig`. Ed25519 by default; spec is signature-algorithm-agnostic. |
| `ts` | yes | ISO-8601 UTC, millisecond precision. The observer's clock at emission. |
| `coin`, `peg` | yes | What was observed against what target. |
| `median_price`, `deviation_bps`, `severity` | yes | Aggregator's output. Independent of source readings — verifiers MUST recompute from `sources` to catch lying observers. |
| `sources[]` | yes | Per-venue readings. At least one. Skew between `ts` here and observation `ts` should be < 60s for the observation to count as fresh. |
| `config` | yes | Reproducibility — a verifier needs to know the thresholds and aggregator to recompute. |
| `sig` | yes | Signature over the canonical JSON form (RFC 8785) of every field except `sig` itself. |

## The aggregator

An **aggregator** is anyone who collects observations from N observers and
computes a quorum view. Aggregators don't need to be trusted either — they
publish their inputs (the raw observations) so anyone can recompute.

Minimum viable aggregation:

```
GIVEN observations O_1 .. O_N for the same (coin, peg) within a 60s window:
  // Drop observations whose recomputed median_price disagrees with the
  // observer's claimed median_price by > 5 bps (lying / buggy observer).
  valid = [o for o in observations if verify(o) and recompute_matches(o)]

  // Quorum threshold — at least 2/3 of declared observers, and at least 3.
  if len(valid) < max(3, ceil(2/3 * declared_set)): emit "indeterminate"; return

  median_of_medians = median(o.median_price for o in valid)
  consensus_bps     = ((median_of_medians - peg) / peg) * 10000
  consensus_sev     = severity_from(abs(consensus_bps), config)
  emit { ts, coin, consensus_price: median_of_medians,
         consensus_bps, consensus_sev, observations: valid }
```

The aggregator's output is itself a verifiable artifact: anyone with the N
raw observations can recompute the quorum view exactly.

## Trust model

| Property | Guarantee |
|---|---|
| **A single observer can't manipulate consensus.** | Quorum threshold (default 2/3) means at least N/3 + 1 observers must collude. |
| **An aggregator can't lie about what observers said.** | Signed observations are published alongside the consensus. Anyone can pull them and recompute. |
| **An observer can't backdate.** | Observations carry an `observer_ts` and aggregators reject observations where `aggregator_received_ts − observer_ts > 60s`. Combined with monotonic source `ts`, replay is bounded. |
| **A source (Binance, Curve, …) can lie.** | Mitigated by source diversity. The cross-source divergence indicator (in the dashboard) flags ticks where sources disagree by > 50 bps so observers can drop suspect inputs. |

## Distribution paths

Observations are publishable over any transport. The three we'll support
first, in roughly increasing trust:

1. **JSONL append to a local file** — `events.jsonl` next to `events.db`.
   The default. An observer's logs are itself the publication.
2. **IPFS / IPNS** — observers pin their observation feed to IPFS; an
   IPNS name points at the latest chunk. Aggregators tail one or more
   IPNS names.
3. **On-chain attestation** — periodic batches anchored to a public chain
   (Ethereum L2 or any EVM chain with reasonable gas). Anchoring gives
   global ordering and timestamping. The chain doesn't *store* every
   observation — it stores the Merkle root of an observation batch, which
   the observer publishes off-chain. Verifiers fetch the off-chain batch
   and check the root.

## How a depeg-monitor instance becomes an observer

Today (already shipped):

```bash
depeg-monitor --config config/default.yaml
# SQLite events.db at cwd, optional Discord/Slack/Telegram alerts
```

Soon (the `observer` mode, not yet implemented but spec'd here):

```bash
# Run as an observer. Generates an Ed25519 keypair on first run, prints
# the public key + DID, writes signed observations as JSONL.
depeg-monitor observer --observer-id did:web:my.host \
    --keyfile ~/.depeg/observer.key \
    --out ./observations.jsonl
```

And to participate in a public aggregator:

```bash
depeg-monitor observer publish --to ipns://<aggregator-key>
```

## In the dashboard

The browser dashboard at `web/index.html` is itself an observer — but a
non-authoritative one, since it can't safely hold a long-lived private key
and a tab can be closed at any moment. It exposes the **same wire format**
on `window.depegMonitor.lastObservations` so a power user can plumb the
output into anything they want (browser extension, local file via the
File System Access API, fetch-to-server). What the dashboard does **not**
do today is sign observations.

## Open questions

These are deliberately unsolved in v0.1 — we want to ship the observation
layer and let real usage shape the answers.

- **Observer set governance.** Who decides which observer_ids count for
  quorum? A static allowlist works for v0.1. A staking/slashing market is
  premature.
- **Source weighting.** Should a Curve TWAP count for more than a
  CoinGecko proxy? For depeg detection of stablecoins, all decent sources
  agree on price within 5–10 bps in calm markets, so naive median is fine.
  Source weighting becomes necessary if/when we extend to thin tokens.
- **Time horizon.** The current spec is point-in-time. Sustained depeg
  (USDT 2022 holding 0.96 for hours vs. USDC SVB 2023 flash-crashing to
  0.88 for minutes) needs different response. The aggregator could emit
  a rolling-window severity in addition to point severity.

## Reading list

- BIS, *Stablecoins: regulation, prudential treatment, and central bank
  digital currencies* (2023)
- NBER, *Stablecoin Runs* (working paper, 2025)
- The 2023 USDC depeg post-mortems from Circle and from independent
  researchers (Llama Risk, Block Analitica, Gauntlet)
- The 2022 UST collapse, in particular the role of curve 4pool liquidity
- Chaos Labs and Gauntlet risk reports for live exchanges (public
  summaries; the underlying signal is paywalled)

## Status

| Layer | State |
|---|---|
| Observation wire format (v1 above) | drafted, this doc |
| Python observer mode (`depeg-monitor observer ...`) | not yet implemented |
| In-browser dashboard exposes wire format | in progress (this PR) |
| JSONL file output | not yet implemented |
| IPFS/IPNS publish | not yet implemented |
| On-chain anchoring | not yet implemented |
| Aggregator reference implementation | not yet implemented |

If you want to claim any of the above, [open an
issue](https://github.com/kcolbchain/depeg-monitor/issues/new) and stake
the work.

## License

[MIT](../LICENSE) — same as the rest of the repo. The spec is intended to
be implemented by anyone who wants to be part of the network.
