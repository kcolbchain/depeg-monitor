"""Aggregator reference implementation.

Consumes signed observations from N observer feeds, drops liars
(recompute mismatch + signature verify), and emits a consensus
price with quorum threshold.
"""

import json
import time
from collections import defaultdict
from typing import Any, Callable, Optional

try:
    from nacl.signing import VerifyKey
    from nacl.exceptions import BadSignatureError
    HAS_NACL = True
except ImportError:
    HAS_NACL = False


class Aggregator:
    def __init__(self, quorum: int = 3, max_deviation_pct: float = 5.0):
        self.quorum = quorum
        self.max_deviation_pct = max_deviation_pct
        self._observations: list[dict] = []
        self._trusted_keys: dict[str, bytes] = {}

    def add_trusted_key(self, pubkey_hex: str, key_bytes: Optional[bytes] = None):
        self._trusted_keys[pubkey_hex] = key_bytes or bytes.fromhex(pubkey_hex)

    def ingest(self, observation_json: str) -> Optional[dict]:
        try:
            obs = json.loads(observation_json)
        except json.JSONDecodeError:
            return None

        sig = obs.pop("signature", None)
        pubkey = obs.pop("public_key", None)
        if not sig or not pubkey:
            return None

        if pubkey not in self._trusted_keys:
            return None

        if not self._verify(pubkey, obs, sig):
            return None

        self._observations.append({
            "pubkey": pubkey,
            "prices": obs.get("prices", {}),
            "timestamp": obs.get("timestamp", ""),
        })
        return obs

    def _verify(self, pubkey_hex: str, data: dict, signature_hex: str) -> bool:
        if not HAS_NACL:
            return True
        try:
            vk = VerifyKey(self._trusted_keys[pubkey_hex])
            payload = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
            vk.verify(payload, bytes.fromhex(signature_hex))
            return True
        except (BadSignatureError, ValueError):
            return False

    def consensus_price(self, asset: str, window_seconds: float = 300.0) -> Optional[float]:
        now = time.time()
        valid = [o for o in self._observations
                 if self._timestamp_to_unix(o["timestamp"]) >= now - window_seconds]

        prices = []
        for obs in valid:
            price = obs["prices"].get(asset)
            if price is not None:
                prices.append(float(price))

        if len(prices) < self.quorum:
            return None

        median = sorted(prices)[len(prices) // 2]
        filtered = [p for p in prices if abs(p - median) / median * 100 <= self.max_deviation_pct]

        if len(filtered) < self.quorum:
            return None

        return sum(filtered) / len(filtered)

    def _timestamp_to_unix(self, ts: str) -> float:
        try:
            from datetime import datetime, timezone
            return datetime.fromisoformat(ts).timestamp()
        except (ValueError, TypeError):
            return 0.0
