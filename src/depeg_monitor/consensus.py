"""Multi-source consensus pegging.

Aggregates per-source stablecoin price readings (DEX TWAP, CEX spot, Curve,
...) into a single *consensus* peg with:

  - a robust consensus price (median — resists a single outlier venue),
  - a signed deviation from the configured peg in basis points,
  - an **agreement score** in ``[0, 1]`` measuring how tightly the venues cluster
    (and how many venues actually reported), and
  - a **severity** label drawn from a small ordered model
    (``normal`` < ``watch`` < ``warning`` < ``critical``).

The module is deliberately pure: it takes plain price readings and config and
returns a frozen :class:`ConsensusResult`. The async monitor and the alert feed
build on top of it but this layer has no I/O, which keeps the math trivially
testable.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Iterable, Sequence


class Severity(IntEnum):
    """Ordered depeg severity. ``IntEnum`` so ``max(...)`` / comparisons work."""

    NORMAL = 0
    WATCH = 1
    WARNING = 2
    CRITICAL = 3

    @property
    def label(self) -> str:
        return self.name.lower()


@dataclass(frozen=True)
class SourceReading:
    """One venue's price observation for a symbol."""

    source: str
    price: float


@dataclass(frozen=True)
class ConsensusThresholds:
    """Deviation thresholds (basis points) for the severity model.

    Defaults mirror the legacy per-source thresholds (50 bps warn / 100 bps
    critical) and add an early ``watch`` tier. ``min_agreement`` is the agreement
    score below which venues are considered to be disagreeing enough that the
    event is escalated by one severity notch (capped at WARNING).
    """

    watch_bps: float = 25.0
    warning_bps: float = 50.0
    critical_bps: float = 100.0
    min_agreement: float = 0.5

    def __post_init__(self) -> None:
        for name in ("watch_bps", "warning_bps", "critical_bps"):
            value = getattr(self, name)
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and non-negative")
        if not (self.watch_bps <= self.warning_bps <= self.critical_bps):
            raise ValueError("thresholds must satisfy watch <= warning <= critical")
        if not (0.0 <= self.min_agreement <= 1.0):
            raise ValueError("min_agreement must be within [0, 1]")


@dataclass(frozen=True)
class ConsensusResult:
    """Outcome of aggregating venue readings into a consensus peg."""

    symbol: str
    peg: float
    consensus_price: float
    deviation_bps: float
    abs_deviation_bps: float
    agreement: float
    severity: Severity
    sources_used: int
    readings: tuple[SourceReading, ...] = field(default_factory=tuple)
    outliers: tuple[SourceReading, ...] = field(default_factory=tuple)

    @property
    def is_depeg(self) -> bool:
        """Whether this result is worth emitting as an alert event."""
        return self.severity >= Severity.WATCH

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "peg": self.peg,
            "consensus_price": self.consensus_price,
            "deviation_bps": self.deviation_bps,
            "abs_deviation_bps": self.abs_deviation_bps,
            "agreement": self.agreement,
            "severity": self.severity.label,
            "sources_used": self.sources_used,
            "readings": [{"source": r.source, "price": r.price} for r in self.readings],
            "outliers": [{"source": r.source, "price": r.price} for r in self.outliers],
        }


def median(values: Sequence[float]) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("median requires at least one value")
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _valid_readings(readings: Iterable[SourceReading]) -> list[SourceReading]:
    """Keep only positive, finite prices (drop None/0/NaN sentinels upstream)."""
    out: list[SourceReading] = []
    for r in readings:
        if isinstance(r.price, (int, float)) and math.isfinite(r.price) and r.price > 0:
            out.append(SourceReading(r.source, float(r.price)))
    return out


def bps_delta(price: float, peg: float) -> float:
    """Signed deviation of ``price`` from ``peg`` in basis points."""
    if peg <= 0 or not math.isfinite(peg):
        raise ValueError("peg must be positive and finite")
    return ((price - peg) / peg) * 10_000.0


FULL_DISAGREEMENT_BPS = 100.0


def agreement_score(readings: Sequence[SourceReading], consensus_price: float) -> float:
    """Confidence that the venues agree, in ``[0, 1]``.

    Combines two factors:

    * **Dispersion** — the relative spread between the highest and lowest venue
      price, in basis points against the consensus. A spread of 0 → 1.0; a spread
      of ``FULL_DISAGREEMENT_BPS`` (default 100 bps = 1%) or more → 0.0, scaled
      linearly in between. Using the full min/max spread (rather than the gap
      from the midpoint, which halves it) means two venues that are 70 bps apart
      register as real disagreement, and a single wildly divergent venue still
      tanks the score.
    * **Quorum** — a single source can never reach full confidence (nothing to
      corroborate it), so one source is capped at 0.5 and two-or-more lift the
      ceiling to 1.0.

    The final score is ``dispersion_factor * quorum_factor``.
    """
    if not readings:
        return 0.0
    if consensus_price <= 0:
        return 0.0

    prices = [r.price for r in readings]
    spread_bps = bps_delta(max(prices), consensus_price) - bps_delta(min(prices), consensus_price)
    dispersion_factor = max(0.0, 1.0 - spread_bps / FULL_DISAGREEMENT_BPS)

    n = len(readings)
    quorum_factor = 0.5 if n == 1 else 1.0

    return round(dispersion_factor * quorum_factor, 4)


def _drop_outliers(
    readings: list[SourceReading], consensus_price: float, outlier_bps: float
) -> tuple[list[SourceReading], list[SourceReading]]:
    """Split readings into (kept, outliers) by distance from the consensus.

    Only trims when there are at least 3 venues — with 2 we have no majority to
    decide which one is wrong, so we keep both and let the agreement score fall.
    """
    if len(readings) < 3:
        return readings, []
    kept: list[SourceReading] = []
    outliers: list[SourceReading] = []
    for r in readings:
        if abs(bps_delta(r.price, consensus_price)) > outlier_bps:
            outliers.append(r)
        else:
            kept.append(r)
    # Never trim everything; if the split removed all, treat none as outliers.
    if not kept:
        return readings, []
    return kept, outliers


def classify_severity(
    abs_deviation_bps: float, agreement: float, thresholds: ConsensusThresholds
) -> Severity:
    """Map a deviation + agreement onto the ordered severity model.

    Deviation drives the base tier. If the venues disagree (agreement below
    ``min_agreement``) the tier is bumped up by one — divergence between venues
    is itself a soft depeg signal — but the disagreement bump alone is capped at
    WARNING so a quiet, low-confidence reading never escalates straight to
    CRITICAL without a genuinely large deviation.
    """
    if abs_deviation_bps >= thresholds.critical_bps:
        base = Severity.CRITICAL
    elif abs_deviation_bps >= thresholds.warning_bps:
        base = Severity.WARNING
    elif abs_deviation_bps >= thresholds.watch_bps:
        base = Severity.WATCH
    else:
        base = Severity.NORMAL

    if agreement < thresholds.min_agreement and base < Severity.CRITICAL:
        bumped = Severity(min(base + 1, Severity.WARNING))
        return max(base, bumped)
    return base


def compute_consensus(
    symbol: str,
    peg: float,
    readings: Iterable[SourceReading],
    thresholds: ConsensusThresholds | None = None,
    outlier_bps: float = 200.0,
) -> ConsensusResult | None:
    """Aggregate venue readings into a consensus peg.

    Returns ``None`` when no usable (positive, finite) reading exists — callers
    should treat that as "no data this cycle", distinct from a healthy peg.
    """
    if peg <= 0 or not math.isfinite(peg):
        raise ValueError("peg must be positive and finite")
    thresholds = thresholds or ConsensusThresholds()

    valid = _valid_readings(readings)
    if not valid:
        return None

    # First pass consensus, then trim gross outliers and recompute so a single
    # broken venue can't drag the consensus price (and the deviation) around.
    provisional = median([r.price for r in valid])
    kept, outliers = _drop_outliers(valid, provisional, outlier_bps)

    consensus_price = median([r.price for r in kept])
    deviation_bps = bps_delta(consensus_price, peg)
    agreement = agreement_score(kept, consensus_price)
    severity = classify_severity(abs(deviation_bps), agreement, thresholds)

    return ConsensusResult(
        symbol=symbol,
        peg=peg,
        consensus_price=consensus_price,
        deviation_bps=deviation_bps,
        abs_deviation_bps=abs(deviation_bps),
        agreement=agreement,
        severity=severity,
        sources_used=len(kept),
        readings=tuple(kept),
        outliers=tuple(outliers),
    )
