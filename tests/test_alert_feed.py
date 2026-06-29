"""Tests for the structured alert feed and its pluggable sinks."""

import json
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from depeg_monitor.alerts.feed import AlertFeed, Sink, StdoutSink, WebhookSink
from depeg_monitor.consensus import Severity, SourceReading, compute_consensus
from depeg_monitor.events import DepegEvent


def make_event(severity_price: float = 0.98, peg: float = 1.0) -> DepegEvent:
    res = compute_consensus(
        "USDC", peg, [SourceReading("binance", severity_price), SourceReading("coinbase", severity_price)]
    )
    return DepegEvent.from_consensus(res, ts="2026-06-30T00:00:00Z")


class CapturingSink(Sink):
    def __init__(self):
        self.events: list[DepegEvent] = []

    async def emit(self, event: DepegEvent) -> None:
        self.events.append(event)


class BoomSink(Sink):
    async def emit(self, event: DepegEvent) -> None:
        raise RuntimeError("sink down")


# --- DepegEvent ---


def test_event_to_dict_is_structured_and_serializable():
    event = make_event()
    d = event.to_dict()
    assert d["schema"] == "depeg-monitor/consensus-event/v1"
    assert d["symbol"] == "USDC"
    assert d["severity"] == "critical"
    assert d["ts"] == "2026-06-30T00:00:00Z"
    assert d["sources"] == ["binance", "coinbase"]
    assert d["deviation_pct"] == pytest.approx(d["deviation_bps"] / 100.0)
    # Must be JSON-serializable for webhook/log sinks.
    json.dumps(d)


def test_event_headline_mentions_severity_symbol_and_sources():
    line = make_event().headline()
    assert "CRITICAL" in line
    assert "USDC" in line
    assert "binance" in line and "coinbase" in line


# --- AlertFeed dispatch ---


@pytest.mark.asyncio
async def test_feed_publishes_to_all_sinks():
    a, b = CapturingSink(), CapturingSink()
    feed = AlertFeed([a, b])
    published = await feed.publish(make_event())
    assert published is True
    assert len(a.events) == 1 and len(b.events) == 1


@pytest.mark.asyncio
async def test_feed_respects_min_severity_floor():
    sink = CapturingSink()
    feed = AlertFeed([sink], min_severity=Severity.CRITICAL)

    # WATCH-level event (small deviation) is below the CRITICAL floor.
    watch_event = make_event(severity_price=0.997)
    assert watch_event.severity < Severity.CRITICAL
    assert await feed.publish(watch_event) is False
    assert sink.events == []

    # CRITICAL event passes.
    assert await feed.publish(make_event(severity_price=0.98)) is True
    assert len(sink.events) == 1


@pytest.mark.asyncio
async def test_feed_isolates_failing_sink():
    good = CapturingSink()
    feed = AlertFeed([BoomSink(), good])
    # A raising sink must not prevent the healthy sink from receiving the event.
    published = await feed.publish(make_event())
    assert published is True
    assert len(good.events) == 1


# --- StdoutSink ---


@pytest.mark.asyncio
async def test_stdout_sink_logs_at_severity_level(caplog):
    with caplog.at_level(logging.CRITICAL, logger="depeg-monitor"):
        await StdoutSink().emit(make_event(severity_price=0.95))
    assert any(r.levelno == logging.CRITICAL for r in caplog.records)
    assert any("USDC" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_stdout_sink_json_mode_emits_parseable_payload(caplog):
    with caplog.at_level(logging.WARNING, logger="depeg-monitor"):
        await StdoutSink(as_json=True).emit(make_event(severity_price=0.994))
    payloads = [json.loads(r.getMessage()) for r in caplog.records]
    assert payloads and payloads[0]["symbol"] == "USDC"


# --- WebhookSink ---


def _mock_session():
    response = MagicMock()
    response.__aenter__ = AsyncMock(return_value=response)
    response.__aexit__ = AsyncMock(return_value=False)
    session = MagicMock()
    session.post = MagicMock(return_value=response)
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return session


@pytest.mark.asyncio
async def test_webhook_sink_posts_full_payload_for_generic():
    session = _mock_session()
    with patch("depeg_monitor.alerts.feed.aiohttp.ClientSession", return_value=session):
        await WebhookSink("https://hook.example/x").emit(make_event())
    _, kwargs = session.post.call_args
    assert session.post.call_args[0][0] == "https://hook.example/x"
    body = kwargs["json"]
    assert body["symbol"] == "USDC"
    assert body["schema"].startswith("depeg-monitor/")


@pytest.mark.asyncio
async def test_webhook_sink_shapes_slack_and_discord_bodies():
    for platform, key in (("slack", "text"), ("discord", "content")):
        session = _mock_session()
        with patch("depeg_monitor.alerts.feed.aiohttp.ClientSession", return_value=session):
            await WebhookSink("https://hook", platform=platform).emit(make_event())
        body = session.post.call_args[1]["json"]
        assert key in body
        assert "USDC" in body[key]


@pytest.mark.asyncio
async def test_webhook_sink_swallows_network_errors():
    failing = MagicMock()
    failing.__aenter__ = AsyncMock(side_effect=OSError("connection refused"))
    failing.__aexit__ = AsyncMock(return_value=False)
    with patch("depeg_monitor.alerts.feed.aiohttp.ClientSession", return_value=failing):
        # Best-effort delivery: must not raise.
        await WebhookSink("https://hook").emit(make_event())
