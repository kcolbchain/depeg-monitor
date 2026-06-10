import json
import math

import pytest
from hypothesis import given, settings, strategies as st
from pydantic import ValidationError

from depeg_monitor.alerts.base import AlertLevel
from depeg_monitor.config import MonitorConfig, StablecoinConfig
from depeg_monitor.fuzzing import (
    TickParseError,
    classify_price,
    median_price,
    parse_price_tick,
    validate_thresholds,
)


finite_prices = st.floats(min_value=0.000001, max_value=10_000, allow_nan=False, allow_infinity=False)
finite_thresholds = st.floats(min_value=0, max_value=10, allow_nan=False, allow_infinity=False)


@given(st.binary(max_size=512))
@settings(max_examples=150)
def test_fuzz_price_tick_ingestion_never_panics(payload):
    try:
        tick = parse_price_tick(payload)
    except TickParseError:
        return

    assert tick.symbol
    assert math.isfinite(tick.price)
    assert tick.price > 0
    assert tick.timestamp >= 0


@given(
    symbol=st.text(min_size=1, max_size=12).filter(lambda s: s.strip() != ""),
    source=st.text(max_size=24),
    price=finite_prices,
    timestamp=st.integers(min_value=0, max_value=2**63 - 1),
)
@settings(max_examples=150)
def test_fuzz_valid_json_ticks_round_trip(symbol, source, price, timestamp):
    payload = json.dumps(
        {
            "symbol": symbol,
            "source": source,
            "price": price,
            "timestamp": timestamp,
        }
    )

    tick = parse_price_tick(payload)

    assert tick.symbol == symbol.strip().upper()
    assert tick.source == (source.strip() or "unknown")
    assert tick.price == price
    assert tick.timestamp == timestamp


@given(
    price=finite_prices,
    peg=finite_prices,
    warn=finite_thresholds,
    critical=finite_thresholds,
)
@settings(max_examples=200)
def test_fuzz_threshold_classifier_matches_monitor_semantics(price, peg, warn, critical):
    if critical < warn:
        with pytest.raises(ValueError):
            validate_thresholds(peg, warn, critical)
        return

    level = classify_price(
        price,
        peg=peg,
        warn_threshold=warn,
        critical_threshold=critical,
    )
    deviation = abs(price - peg) / peg

    if deviation >= critical:
        assert level == AlertLevel.CRITICAL
    elif deviation >= warn:
        assert level == AlertLevel.WARN
    else:
        assert level is None


@given(
    peg=finite_prices,
    warn=st.floats(min_value=0.000001, max_value=0.25, allow_nan=False, allow_infinity=False),
    offsets=st.lists(st.floats(min_value=-0.99, max_value=0.99, allow_nan=False, allow_infinity=False), min_size=1),
)
@settings(max_examples=150)
def test_fuzz_in_range_state_sequence_never_alerts(peg, warn, offsets):
    critical = warn * 2

    for offset in offsets:
        bounded = max(min(offset, warn * 0.99), -warn * 0.99)
        price = peg * (1 + bounded)
        assert classify_price(price, peg=peg, warn_threshold=warn, critical_threshold=critical) is None


@given(
    readings=st.dictionaries(
        keys=st.text(min_size=1, max_size=12),
        values=finite_prices,
        min_size=1,
        max_size=9,
    )
)
@settings(max_examples=150)
def test_fuzz_multi_source_median_is_order_independent(readings):
    ordered = list(readings.items())
    reversed_order = list(reversed(ordered))

    assert median_price(ordered) == median_price(reversed_order)
    assert median_price(readings) == median_price(ordered)


@given(
    peg=st.one_of(st.just(0.0), st.just(-1.0), st.just(float("nan")), st.just(float("inf"))),
    warn=finite_thresholds,
    critical=finite_thresholds,
)
def test_fuzz_malformed_config_rejects_bad_peg(peg, warn, critical):
    with pytest.raises((ValidationError, ValueError)):
        StablecoinConfig(symbol="USDC", peg=peg, warn_threshold=warn, critical_threshold=critical)


@given(interval=st.integers(max_value=0))
def test_fuzz_malformed_config_rejects_bad_interval(interval):
    with pytest.raises(ValidationError):
        MonitorConfig(interval_seconds=interval)
