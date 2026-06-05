"""Reference aggregator for depeg oracle observation feeds."""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import math
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import yaml

try:
    from nacl.exceptions import BadSignatureError
    from nacl.signing import VerifyKey
except ImportError:  # pragma: no cover - dependency is declared in pyproject
    BadSignatureError = Exception
    VerifyKey = None


OBSERVATION_SCHEMA = "depeg-oracle/observation/v1"
CONSENSUS_SCHEMA = "depeg-oracle/consensus/v1"
RECOMPUTE_TOLERANCE_BPS = 5.0


@dataclass(frozen=True)
class ObserverFeed:
    observer_id: str
    observer_pubkey: str
    source: str


@dataclass(frozen=True)
class CandidateObservation:
    feed: ObserverFeed
    observation: dict[str, Any]
    observation_hash: str
    ts_epoch: float
    window_start: int
    coin: str
    peg: float


def canonical_json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def unsigned_payload(observation: dict[str, Any]) -> dict[str, Any]:
    payload = dict(observation)
    payload.pop("sig", None)
    payload.pop("signature", None)
    return payload


def observation_hash(observation: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(observation)).hexdigest()


def _decode_key_material(value: str, prefix: str | None = None) -> bytes:
    if prefix and value.startswith(f"{prefix}:"):
        value = value.split(":", 1)[1]
    value = value.strip()
    if not value:
        raise ValueError("empty key material")
    try:
        return bytes.fromhex(value)
    except ValueError:
        return base64.b64decode(value, validate=True)


def _decode_signature(value: str) -> bytes:
    return _decode_key_material(value, "ed25519")


def _decode_pubkey(value: str) -> bytes:
    return _decode_key_material(value, "ed25519")


def verify_observation_signature(observation: dict[str, Any], observer_pubkey: str) -> bool:
    """Verify the observation signature against the configured Ed25519 pubkey."""
    if VerifyKey is None:
        return False
    signature = observation.get("sig") or observation.get("signature")
    if not isinstance(signature, str):
        return False

    try:
        configured_key = _decode_pubkey(observer_pubkey)
        observed_pubkey = observation.get("observer_pubkey")
        if isinstance(observed_pubkey, str) and _decode_pubkey(observed_pubkey) != configured_key:
            return False
        VerifyKey(configured_key).verify(canonical_json_bytes(unsigned_payload(observation)), _decode_signature(signature))
        return True
    except (BadSignatureError, ValueError, binascii.Error):
        return False


def parse_ts(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        raise ValueError("timestamp must be ISO-8601 string or epoch seconds")
    normalized = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized).timestamp()


def iso_utc(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def median(values: Iterable[float]) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("median requires at least one value")
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def bps_delta(price: float, peg: float) -> float:
    if peg <= 0 or not math.isfinite(peg):
        raise ValueError("peg must be positive and finite")
    return ((price - peg) / peg) * 10_000


def severity_from_bps(abs_bps: float, warn_bps: float = 50.0, critical_bps: float = 100.0) -> str:
    if abs_bps >= critical_bps:
        return "critical"
    if abs_bps >= warn_bps:
        return "warn"
    return "normal"


def recompute_median_price(observation: dict[str, Any]) -> float:
    sources = observation.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError("observation must include non-empty sources")
    prices: list[float] = []
    for source in sources:
        if not isinstance(source, dict):
            continue
        price = source.get("price")
        if isinstance(price, (int, float)) and math.isfinite(float(price)):
            prices.append(float(price))
    if not prices:
        raise ValueError("sources must include at least one finite price")
    return median(prices)


def claimed_price_matches_sources(observation: dict[str, Any], tolerance_bps: float = RECOMPUTE_TOLERANCE_BPS) -> bool:
    try:
        claimed = float(observation["median_price"])
        peg = float(observation["peg"])
        recomputed = recompute_median_price(observation)
        return abs(claimed - recomputed) / peg * 10_000 <= tolerance_bps
    except (KeyError, TypeError, ValueError):
        return False


def load_observer_feeds(feeds_path: str | Path | None, feed_args: list[str] | None = None) -> list[ObserverFeed]:
    raw_feeds: list[dict[str, Any]] = []

    if feeds_path:
        with open(feeds_path, encoding="utf-8") as f:
            loaded = yaml.safe_load(f) or []
        if isinstance(loaded, dict):
            loaded = loaded.get("observers") or loaded.get("feeds") or []
        if not isinstance(loaded, list):
            raise ValueError("feeds YAML must be a list or contain observers:/feeds:")
        raw_feeds.extend(loaded)

    for feed_arg in feed_args or []:
        pieces = feed_arg.split(",", 2)
        if len(pieces) != 3:
            raise ValueError("--feed must be observer_id,observer_pubkey,source")
        raw_feeds.append({"observer_id": pieces[0], "observer_pubkey": pieces[1], "source": pieces[2]})

    feeds = [
        ObserverFeed(
            observer_id=str(raw["observer_id"]),
            observer_pubkey=str(raw["observer_pubkey"]),
            source=str(raw["source"]),
        )
        for raw in raw_feeds
    ]
    if not feeds:
        raise ValueError("at least one observer feed is required")
    return feeds


def load_jsonl_source(source: str) -> list[dict[str, Any]]:
    if source.startswith(("http://", "https://")):
        with urllib.request.urlopen(source, timeout=10) as response:
            lines = response.read().decode("utf-8").splitlines()
    else:
        lines = Path(source).read_text(encoding="utf-8").splitlines()
    observations: list[dict[str, Any]] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        loaded = json.loads(line)
        if isinstance(loaded, dict):
            observations.append(loaded)
    return observations


def _candidate_from_observation(feed: ObserverFeed, observation: dict[str, Any], window_seconds: int) -> CandidateObservation | None:
    try:
        if observation.get("schema", OBSERVATION_SCHEMA) != OBSERVATION_SCHEMA:
            return None
        if observation.get("observer_id") != feed.observer_id:
            return None
        ts_epoch = parse_ts(observation["ts"])
        peg = float(observation["peg"])
        coin = str(observation["coin"])
        window_start = int(ts_epoch // window_seconds) * window_seconds
        return CandidateObservation(feed, observation, observation_hash(observation), ts_epoch, window_start, coin, peg)
    except (KeyError, TypeError, ValueError):
        return None


def collect_candidates(feeds: list[ObserverFeed], window_seconds: int) -> list[CandidateObservation]:
    candidates: list[CandidateObservation] = []
    for feed in feeds:
        for observation in load_jsonl_source(feed.source):
            candidate = _candidate_from_observation(feed, observation, window_seconds)
            if candidate is not None:
                candidates.append(candidate)
    return candidates


def _latest_per_observer(candidates: list[CandidateObservation]) -> list[CandidateObservation]:
    latest: dict[str, CandidateObservation] = {}
    for candidate in candidates:
        previous = latest.get(candidate.feed.observer_id)
        if previous is None or candidate.ts_epoch > previous.ts_epoch:
            latest[candidate.feed.observer_id] = candidate
    return list(latest.values())


def _observation_ref(candidate: CandidateObservation) -> dict[str, str]:
    observation_id = candidate.observation.get("observation_id") or candidate.observation.get("id")
    if observation_id is None:
        observation_id = candidate.observation_hash[:16]
    return {
        "observer_id": candidate.feed.observer_id,
        "observation_id": str(observation_id),
        "hash": candidate.observation_hash,
    }


def _drop_ref(candidate: CandidateObservation, reason: str) -> dict[str, str]:
    ref = _observation_ref(candidate)
    ref["reason"] = reason
    return ref


def _validation_status(candidate: CandidateObservation) -> str | None:
    if not verify_observation_signature(candidate.observation, candidate.feed.observer_pubkey):
        return "invalid signature"
    if not claimed_price_matches_sources(candidate.observation):
        return "median recompute mismatch"
    return None


def aggregate_observations(
    feeds: list[ObserverFeed],
    window_seconds: int = 60,
    quorum_ratio: float = 2 / 3,
) -> list[dict[str, Any]]:
    if window_seconds <= 0:
        raise ValueError("window_seconds must be positive")
    if quorum_ratio <= 0 or quorum_ratio > 1:
        raise ValueError("quorum_ratio must be within (0, 1]")

    quorum = max(3, math.ceil(quorum_ratio * len(feeds)))
    groups: dict[tuple[str, float, int], list[CandidateObservation]] = {}
    for candidate in collect_candidates(feeds, window_seconds):
        groups.setdefault((candidate.coin, candidate.peg, candidate.window_start), []).append(candidate)

    records: list[dict[str, Any]] = []
    for (coin, peg, window_start), candidates in sorted(groups.items(), key=lambda item: item[0]):
        dropped: list[dict[str, str]] = []
        valid: list[CandidateObservation] = []
        for candidate in _latest_per_observer(candidates):
            reason = _validation_status(candidate)
            if reason:
                dropped.append(_drop_ref(candidate, reason))
            else:
                valid.append(candidate)

        base_record: dict[str, Any] = {
            "schema": CONSENSUS_SCHEMA,
            "ts": iso_utc(max((candidate.ts_epoch for candidate in candidates), default=window_start)),
            "window_start": iso_utc(window_start),
            "window_seconds": window_seconds,
            "coin": coin,
            "peg": peg,
            "declared_observers": len(feeds),
            "quorum": quorum,
            "valid_observers": len(valid),
            "observations": [_observation_ref(candidate) for candidate in valid],
            "dropped_observations": dropped,
        }

        if len(valid) < quorum:
            base_record.update({"status": "indeterminate", "reason": "insufficient observers"})
            records.append(base_record)
            continue

        consensus_price = median(float(candidate.observation["median_price"]) for candidate in valid)
        consensus_bps = bps_delta(consensus_price, peg)
        config = valid[0].observation.get("config") if valid else {}
        warn_bps = float(config.get("warn_threshold_bps", 50.0)) if isinstance(config, dict) else 50.0
        critical_bps = float(config.get("critical_threshold_bps", 100.0)) if isinstance(config, dict) else 100.0
        base_record.update(
            {
                "status": "consensus",
                "consensus_price": consensus_price,
                "consensus_bps": consensus_bps,
                "severity": severity_from_bps(abs(consensus_bps), warn_bps, critical_bps),
            }
        )
        records.append(base_record)

    return records


def write_consensus(records: list[dict[str, Any]], out_path: str | Path, manifest_path: str | Path | None = None) -> Path:
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")

    manifest = Path(manifest_path) if manifest_path else out.with_suffix(out.suffix + ".manifest.json")
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest_records = [
        {
            "record_hash": observation_hash(record),
            "coin": record["coin"],
            "peg": record["peg"],
            "window_start": record["window_start"],
            "status": record["status"],
            "input_observation_hashes": [item["hash"] for item in record["observations"]],
        }
        for record in records
    ]
    manifest.write_text(
        json.dumps(
            {
                "schema": "depeg-oracle/consensus-manifest/v1",
                "record_count": len(records),
                "records": manifest_records,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="depeg-monitor aggregator run")
    parser.add_argument("--feeds", help="YAML file containing observer feeds")
    parser.add_argument("--feed", action="append", default=[], help="observer_id,observer_pubkey,source")
    parser.add_argument("--window-seconds", type=int, default=60)
    parser.add_argument("--quorum-ratio", type=float, default=2 / 3)
    parser.add_argument("--out", required=True, help="Consensus JSONL output path")
    parser.add_argument("--manifest-out", help="Sidecar manifest output path")
    return parser


def run_aggregator_cli(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    feeds = load_observer_feeds(args.feeds, args.feed)
    records = aggregate_observations(feeds, args.window_seconds, args.quorum_ratio)
    write_consensus(records, args.out, args.manifest_out)
    return 0
