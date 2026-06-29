"""Structured depeg event model emitted by the consensus alert feed."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from .consensus import ConsensusResult, Severity

EVENT_SCHEMA = "depeg-monitor/consensus-event/v1"


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class DepegEvent:
    """A single structured depeg observation ready for a sink.

    Wraps a :class:`~depeg_monitor.consensus.ConsensusResult` with a timestamp
    and schema tag so downstream sinks (webhook, stdout, future DB/Kafka) get a
    stable, self-describing payload.
    """

    symbol: str
    severity: Severity
    consensus_price: float
    peg: float
    deviation_bps: float
    agreement: float
    sources_used: int
    sources: tuple[str, ...]
    ts: str = ""

    @classmethod
    def from_consensus(cls, result: ConsensusResult, ts: str | None = None) -> "DepegEvent":
        return cls(
            symbol=result.symbol,
            severity=result.severity,
            consensus_price=result.consensus_price,
            peg=result.peg,
            deviation_bps=result.deviation_bps,
            agreement=result.agreement,
            sources_used=result.sources_used,
            sources=tuple(r.source for r in result.readings),
            ts=ts or _now_iso(),
        )

    @property
    def deviation_pct(self) -> float:
        return self.deviation_bps / 100.0

    def headline(self) -> str:
        """Human-readable one-liner shared by stdout and webhook sinks."""
        return (
            f"[{self.severity.label.upper()}] {self.symbol} consensus "
            f"${self.consensus_price:.6f} (peg ${self.peg:g}, "
            f"{self.deviation_bps:+.1f} bps, agreement {self.agreement:.0%}) "
            f"across {self.sources_used} source(s): {', '.join(self.sources)}"
        )

    def to_dict(self) -> dict:
        return {
            "schema": EVENT_SCHEMA,
            "ts": self.ts,
            "symbol": self.symbol,
            "severity": self.severity.label,
            "consensus_price": self.consensus_price,
            "peg": self.peg,
            "deviation_bps": self.deviation_bps,
            "deviation_pct": self.deviation_pct,
            "agreement": self.agreement,
            "sources_used": self.sources_used,
            "sources": list(self.sources),
            "message": self.headline(),
        }
