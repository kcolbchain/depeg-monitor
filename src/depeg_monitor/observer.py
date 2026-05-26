"""Server-side observer mode with Ed25519 signing + JSONL output.

Per docs/DEPEG_ORACLES.md - the authoritative observer mode that:
- Runs as a standalone process or daemon
- Fetches prices from configured sources at regular intervals
- Signs observations with Ed25519 keypair
- Outputs JSONL to stdout or a file
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

try:
    from nacl.signing import SigningKey
    HAS_NACL = True
except ImportError:
    HAS_NACL = False


def _load_or_generate_key(key_path: Path) -> bytes:
    if key_path.exists():
        return key_path.read_bytes()
    if not HAS_NACL:
        raise ImportError("pynacl required: pip install pynacl")
    key = SigningKey.generate()
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_bytes(bytes(key))
    return bytes(key)


def _sign_observation(key_bytes: bytes, observation: dict) -> str:
    if not HAS_NACL:
        raise ImportError("pynacl required: pip install pynacl")
    sk = SigningKey(key_bytes)
    data = json.dumps(observation, sort_keys=True, separators=(",", ":")).encode()
    sig = sk.sign(data)
    return sig.signature.hex()


def create_observer(source_fn, key_path: Path = Path(".observer_key"), interval: int = 60):
    """Create and return an observer that fetches, signs, and outputs."""
    key_bytes = _load_or_generate_key(key_path)

    def observe() -> dict:
        prices = source_fn() if callable(source_fn) else {}
        observation = {
            "type": "price_observation",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "prices": prices,
        }
        signature = _sign_observation(key_bytes, observation)
        observation["signature"] = signature
        observation["public_key"] = bytes(SigningKey(key_bytes).verify_key).hex()
        return observation

    return observe


def run_observer_loop(observe_fn, output: str = "stdout", interval: int = 60):
    """Run observer loop, outputting JSONL."""
    while True:
        obs = observe_fn()
        line = json.dumps(obs, separators=(",", ":"))
        if output == "stdout":
            print(line, flush=True)
        elif output == "stderr":
            print(line, file=sys.stderr, flush=True)
        else:
            with open(output, "a") as f:
                f.write(line + "
")
        time.sleep(interval)


def main():
    parser = argparse.ArgumentParser(description="Server-side observer mode")
    parser.add_argument("--key-path", default=".observer_key", help="Path to Ed25519 key file")
    parser.add_argument("--output", default="stdout", choices=["stdout", "stderr", "file"],
                        help="Output destination")
    parser.add_argument("--output-file", default="observations.jsonl", help="Output file path")
    parser.add_argument("--interval", type=int, default=60, help="Observation interval in seconds")
    args = parser.parse_args()

    try:
        from depeg_monitor.sources.cex import CEXSource
        source = CEXSource()
        observe_fn = create_observer(lambda: source.fetch(), Path(args.key_path), args.interval)
        run_observer_loop(observe_fn, args.output_file if args.output == "file" else args.output, args.interval)
    except ImportError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
