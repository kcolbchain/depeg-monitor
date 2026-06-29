"""Tests for multi-source consensus pegging math and the severity model."""

import math

import pytest

from depeg_monitor.consensus import (
    ConsensusThresholds,
    Severity,
    SourceReading,
    agreement_score,
    bps_delta,
    classify_severity,
    compute_consensus,
    median,
)


def R(source: str, price: float) -> SourceReading:
    return SourceReading(source, price)


# --- median / bps helpers ---


def test_median_odd_and_even():
    assert median([1.0]) == 1.0
    assert median([3.0, 1.0, 2.0]) == 2.0
    assert median([1.0, 2.0, 3.0, 4.0]) == 2.5


def test_median_empty_raises():
    with pytest.raises(ValueError):
        median([])


def test_bps_delta_signed():
    assert bps_delta(1.0, 1.0) == 0.0
    assert bps_delta(1.01, 1.0) == pytest.approx(100.0)
    assert bps_delta(0.99, 1.0) == pytest.approx(-100.0)


def test_bps_delta_rejects_bad_peg():
    for bad in (0.0, -1.0, math.inf, math.nan):
        with pytest.raises(ValueError):
            bps_delta(1.0, bad)


# --- agreement score ---


def test_agreement_perfect_when_sources_identical():
    readings = [R("a", 1.0), R("b", 1.0), R("c", 1.0)]
    assert agreement_score(readings, 1.0) == 1.0


def test_agreement_single_source_capped_at_half():
    # One source can't corroborate itself, so confidence is capped at 0.5.
    assert agreement_score([R("a", 1.0)], 1.0) == 0.5


def test_agreement_falls_with_dispersion():
    tight = agreement_score([R("a", 1.0), R("b", 1.0005)], 1.0)
    loose = agreement_score([R("a", 1.0), R("b", 1.005)], 1.0)
    assert 0.0 <= loose < tight <= 1.0


def test_agreement_zero_when_a_venue_diverges_one_percent():
    # 100 bps gap from consensus -> dispersion factor floors at 0.
    assert agreement_score([R("a", 1.0), R("b", 1.01)], 1.0) == 0.0


def test_agreement_empty_is_zero():
    assert agreement_score([], 1.0) == 0.0


# --- severity model ---


def test_severity_tiers_by_deviation():
    t = ConsensusThresholds()
    high_agreement = 1.0
    assert classify_severity(0.0, high_agreement, t) == Severity.NORMAL
    assert classify_severity(25.0, high_agreement, t) == Severity.WATCH
    assert classify_severity(50.0, high_agreement, t) == Severity.WARNING
    assert classify_severity(100.0, high_agreement, t) == Severity.CRITICAL
    assert classify_severity(500.0, high_agreement, t) == Severity.CRITICAL


def test_severity_boundaries_are_inclusive():
    t = ConsensusThresholds(watch_bps=25, warning_bps=50, critical_bps=100)
    assert classify_severity(24.99, 1.0, t) == Severity.NORMAL
    assert classify_severity(25.0, 1.0, t) == Severity.WATCH
    assert classify_severity(49.99, 1.0, t) == Severity.WATCH
    assert classify_severity(50.0, 1.0, t) == Severity.WARNING


def test_low_agreement_bumps_one_tier_but_not_past_warning():
    t = ConsensusThresholds(min_agreement=0.5)
    # Normal deviation + disagreeing venues -> escalate to WATCH.
    assert classify_severity(0.0, 0.1, t) == Severity.WATCH
    # Watch deviation + disagreement -> WARNING.
    assert classify_severity(25.0, 0.1, t) == Severity.WARNING
    # Warning deviation + disagreement -> capped at WARNING (no jump to CRITICAL).
    assert classify_severity(50.0, 0.1, t) == Severity.WARNING


def test_low_agreement_never_demotes_real_critical():
    t = ConsensusThresholds()
    assert classify_severity(150.0, 0.0, t) == Severity.CRITICAL


def test_thresholds_validation():
    with pytest.raises(ValueError):
        ConsensusThresholds(warning_bps=10, watch_bps=20)  # out of order
    with pytest.raises(ValueError):
        ConsensusThresholds(min_agreement=1.5)
    with pytest.raises(ValueError):
        ConsensusThresholds(watch_bps=-1)


# --- compute_consensus end to end ---


def test_consensus_healthy_peg_is_normal():
    res = compute_consensus("USDC", 1.0, [R("binance", 1.0), R("coinbase", 1.0003), R("curve", 0.9998)])
    assert res is not None
    assert res.severity == Severity.NORMAL
    assert res.is_depeg is False
    assert res.sources_used == 3
    assert res.consensus_price == pytest.approx(1.0, abs=1e-3)
    assert res.agreement > 0.9


def test_consensus_critical_when_all_sources_low():
    res = compute_consensus("USDC", 1.0, [R("binance", 0.980), R("coinbase", 0.9802), R("curve", 0.9798)])
    assert res.severity == Severity.CRITICAL
    assert res.is_depeg is True
    assert res.deviation_bps < 0
    assert res.abs_deviation_bps == pytest.approx(abs(res.deviation_bps))
    assert res.agreement > 0.9  # tight cluster: they agree it's depegged


def test_consensus_median_resists_single_outlier():
    # Two venues say ~peg, one says 0.50. Median keeps consensus near 1.0 and
    # the gross outlier is trimmed (>=3 sources), so deviation stays small.
    res = compute_consensus(
        "USDT", 1.0, [R("binance", 1.0001), R("coinbase", 0.9999), R("bad-venue", 0.50)]
    )
    assert res.consensus_price == pytest.approx(1.0, abs=1e-3)
    assert {o.source for o in res.outliers} == {"bad-venue"}
    assert res.sources_used == 2


def test_consensus_two_sources_disagree_escalates_via_agreement():
    # Only two venues, far apart, neither trimmed (no majority) -> low agreement
    # bumps severity even though the median deviation is modest. With a 70 bps
    # split the consensus sits at the midpoint (~35 bps each side of it), so the
    # agreement score drops below the 0.5 floor and the event is escalated.
    res = compute_consensus("DAI", 1.0, [R("binance", 1.0), R("curve", 1.007)])
    assert res.sources_used == 2
    assert res.outliers == ()
    assert res.agreement < 0.5
    assert res.severity >= Severity.WARNING


def test_consensus_filters_nonpositive_and_nonfinite():
    res = compute_consensus(
        "USDC",
        1.0,
        [R("a", 0.0), R("b", -1.0), R("c", float("nan")), R("d", 1.0), R("e", 1.0002)],
    )
    assert res is not None
    assert res.sources_used == 2
    assert {r.source for r in res.readings} == {"d", "e"}


def test_consensus_returns_none_when_no_valid_readings():
    assert compute_consensus("USDC", 1.0, [R("a", 0.0), R("b", float("nan"))]) is None
    assert compute_consensus("USDC", 1.0, []) is None


def test_consensus_rejects_bad_peg():
    with pytest.raises(ValueError):
        compute_consensus("USDC", 0.0, [R("a", 1.0)])


def test_consensus_to_dict_round_trips_fields():
    res = compute_consensus("USDC", 1.0, [R("binance", 0.985), R("coinbase", 0.986)])
    d = res.to_dict()
    assert d["symbol"] == "USDC"
    assert d["severity"] == res.severity.label
    assert d["sources_used"] == res.sources_used
    assert [r["source"] for r in d["readings"]] == ["binance", "coinbase"]
