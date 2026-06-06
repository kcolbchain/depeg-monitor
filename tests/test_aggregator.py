import json
from pathlib import Path

import yaml
from nacl.signing import SigningKey

from depeg_monitor.aggregator import (
    aggregate_observations,
    load_observer_feeds,
    observation_hash,
    run_aggregator_cli,
)


def _signed_observation(
    key: SigningKey,
    observer_id: str,
    ts: str,
    median_price: float,
    source_prices: list[float],
) -> dict:
    observation = {
        "schema": "depeg-oracle/observation/v1",
        "observer_id": observer_id,
        "observer_pubkey": f"ed25519:{bytes(key.verify_key).hex()}",
        "ts": ts,
        "coin": "USDC",
        "peg": 1.0,
        "median_price": median_price,
        "deviation_bps": (median_price - 1.0) * 10_000,
        "severity": "normal",
        "sources": [
            {"name": f"source-{index}", "pair": "USDC-USD", "price": price, "ts": ts}
            for index, price in enumerate(source_prices)
        ],
        "config": {
            "warn_threshold_bps": 50,
            "critical_threshold_bps": 100,
            "aggregator": "median",
        },
    }
    payload = json.dumps(observation, sort_keys=True, separators=(",", ":")).encode()
    observation["sig"] = f"ed25519:{key.sign(payload).signature.hex()}"
    return observation


def _write_feed(path: Path, observations: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(observation, sort_keys=True, separators=(",", ":")) + "\n" for observation in observations),
        encoding="utf-8",
    )


def _feeds_config(tmp_path: Path, feed_count: int = 3) -> tuple[Path, list[SigningKey]]:
    keys = [SigningKey.generate() for _ in range(feed_count)]
    feeds = []
    for index, key in enumerate(keys):
        source = tmp_path / f"observer-{index}.jsonl"
        feeds.append(
            {
                "observer_id": f"observer-{index}",
                "observer_pubkey": f"ed25519:{bytes(key.verify_key).hex()}",
                "source": str(source),
            }
        )
    config = tmp_path / "observers.yaml"
    config.write_text(yaml.safe_dump({"observers": feeds}), encoding="utf-8")
    return config, keys


def test_aggregator_round_trips_verifiable_observations(tmp_path):
    feeds_path, keys = _feeds_config(tmp_path, 3)
    observations = [
        _signed_observation(keys[0], "observer-0", "2026-05-24T14:21:03Z", 0.9940, [0.9939, 0.9940, 0.9941]),
        _signed_observation(keys[1], "observer-1", "2026-05-24T14:21:05Z", 0.9942, [0.9941, 0.9942, 0.9943]),
        _signed_observation(keys[2], "observer-2", "2026-05-24T14:21:06Z", 0.9944, [0.9943, 0.9944, 0.9945]),
    ]
    for index, observation in enumerate(observations):
        _write_feed(tmp_path / f"observer-{index}.jsonl", [observation])

    records = aggregate_observations(load_observer_feeds(feeds_path), window_seconds=60)

    assert len(records) == 1
    record = records[0]
    assert record["status"] == "consensus"
    assert record["consensus_price"] == 0.9942
    assert record["valid_observers"] == 3
    assert [item["hash"] for item in record["observations"]] == [observation_hash(item) for item in observations]


def test_aggregator_drops_lying_observer_and_keeps_quorum(tmp_path):
    feeds_path, keys = _feeds_config(tmp_path, 4)
    honest = [
        _signed_observation(keys[0], "observer-0", "2026-05-24T14:21:03Z", 0.9940, [0.9939, 0.9940, 0.9941]),
        _signed_observation(keys[1], "observer-1", "2026-05-24T14:21:04Z", 0.9942, [0.9941, 0.9942, 0.9943]),
        _signed_observation(keys[2], "observer-2", "2026-05-24T14:21:05Z", 0.9944, [0.9943, 0.9944, 0.9945]),
    ]
    liar = _signed_observation(keys[3], "observer-3", "2026-05-24T14:21:06Z", 0.9995, [0.9942, 0.9943, 0.9944])
    for index, observation in enumerate([*honest, liar]):
        _write_feed(tmp_path / f"observer-{index}.jsonl", [observation])

    record = aggregate_observations(load_observer_feeds(feeds_path), window_seconds=60)[0]

    assert record["status"] == "consensus"
    assert record["valid_observers"] == 3
    assert record["consensus_price"] == 0.9942
    assert record["dropped_observations"] == [
        {
            "observer_id": "observer-3",
            "observation_id": observation_hash(liar)[:16],
            "hash": observation_hash(liar),
            "reason": "median recompute mismatch",
        }
    ]


def test_aggregator_drops_invalid_signature(tmp_path):
    feeds_path, keys = _feeds_config(tmp_path, 4)
    valid_observations = [
        _signed_observation(keys[0], "observer-0", "2026-05-24T14:21:03Z", 0.9940, [0.9939, 0.9940, 0.9941]),
        _signed_observation(keys[1], "observer-1", "2026-05-24T14:21:04Z", 0.9942, [0.9941, 0.9942, 0.9943]),
        _signed_observation(keys[2], "observer-2", "2026-05-24T14:21:05Z", 0.9944, [0.9943, 0.9944, 0.9945]),
    ]
    bad_sig = _signed_observation(keys[3], "observer-3", "2026-05-24T14:21:06Z", 0.9942, [0.9941, 0.9942, 0.9943])
    bad_sig["sig"] = "ed25519:" + "00" * 64
    for index, observation in enumerate([*valid_observations, bad_sig]):
        _write_feed(tmp_path / f"observer-{index}.jsonl", [observation])

    record = aggregate_observations(load_observer_feeds(feeds_path), window_seconds=60)[0]

    assert record["status"] == "consensus"
    assert record["valid_observers"] == 3
    assert record["dropped_observations"][0]["observer_id"] == "observer-3"
    assert record["dropped_observations"][0]["reason"] == "invalid signature"


def test_aggregator_handles_missing_observers_as_indeterminate(tmp_path):
    feeds_path, keys = _feeds_config(tmp_path, 4)
    for index in range(2):
        observation = _signed_observation(
            keys[index],
            f"observer-{index}",
            "2026-05-24T14:21:03Z",
            0.9940 + index * 0.0002,
            [0.9939 + index * 0.0002, 0.9940 + index * 0.0002, 0.9941 + index * 0.0002],
        )
        _write_feed(tmp_path / f"observer-{index}.jsonl", [observation])
    for index in (2, 3):
        _write_feed(tmp_path / f"observer-{index}.jsonl", [])

    record = aggregate_observations(load_observer_feeds(feeds_path), window_seconds=60)[0]

    assert record["status"] == "indeterminate"
    assert record["reason"] == "insufficient observers"
    assert record["valid_observers"] == 2
    assert record["quorum"] == 3


def test_aggregator_cli_writes_jsonl_and_manifest(tmp_path):
    feeds_path, keys = _feeds_config(tmp_path, 3)
    for index, key in enumerate(keys):
        observation = _signed_observation(
            key,
            f"observer-{index}",
            "2026-05-24T14:21:03Z",
            0.9940 + index * 0.0001,
            [0.9939 + index * 0.0001, 0.9940 + index * 0.0001, 0.9941 + index * 0.0001],
        )
        _write_feed(tmp_path / f"observer-{index}.jsonl", [observation])

    out = tmp_path / "consensus.jsonl"
    manifest = tmp_path / "manifest.json"

    assert run_aggregator_cli(["--feeds", str(feeds_path), "--out", str(out), "--manifest-out", str(manifest)]) == 0
    record = json.loads(out.read_text(encoding="utf-8").strip())
    manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))

    assert record["status"] == "consensus"
    assert manifest_payload["record_count"] == 1
    assert manifest_payload["records"][0]["input_observation_hashes"] == [
        item["hash"] for item in record["observations"]
    ]
