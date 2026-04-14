"""Tests for Telegram alert channel."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from depeg_monitor.alerts.telegram import TelegramAlert
from depeg_monitor.alerts.base import AlertLevel


class TestTelegramAlert:

    def _make_alert(self, token: str = "123456:ABC-DEF", chat_id: str = "-100123456") -> TelegramAlert:
        return TelegramAlert(token, chat_id)

    def test_init(self):
        alert = self._make_alert("test_token", "test_chat")
        assert alert._token == "test_token"
        assert alert._chat_id == "test_chat"

    @pytest.mark.asyncio
    async def test_send_success(self):
        """Test successful message send."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"ok": True, "result": {"message_id": 1}})
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_response)
        mock_session.closed = False

        alert = self._make_alert()

        with patch.object(alert, "_get_session", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_session
            await alert.send(AlertLevel.WARN, "USDC", 0.995, 1.0, "binance")

    @pytest.mark.asyncio
    async def test_send_critical(self):
        """Critical alerts should include attention text."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"ok": True})
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_response)
        mock_session.closed = False

        alert = self._make_alert()

        with patch.object(alert, "_get_session", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_session
            await alert.send(AlertLevel.CRITICAL, "USDC", 0.98, 1.0, "binance")

    @pytest.mark.asyncio
    async def test_send_invalid_token(self):
        """Invalid bot token should not crash."""
        mock_response = MagicMock()
        mock_response.status = 401
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_response)
        mock_session.closed = False

        alert = self._make_alert()

        with patch.object(alert, "_get_session", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_session
            await alert.send(AlertLevel.WARN, "USDC", 0.99, 1.0, "binance")

    @pytest.mark.asyncio
    async def test_send_rate_limited(self):
        """Rate limit should be handled gracefully."""
        mock_response = MagicMock()
        mock_response.status = 429
        mock_response.headers = {"Retry-After": "60"}
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_response)
        mock_session.closed = False

        alert = self._make_alert()

        with patch.object(alert, "_get_session", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_session
            await alert.send(AlertLevel.WARN, "USDC", 0.99, 1.0, "binance")

    def test_format_message_warn(self):
        """Test message formatting for WARN level."""
        alert = self._make_alert()
        msg = alert._format_message(AlertLevel.WARN, "USDC", 0.993, 1.0, "binance")

        assert "USDC" in msg
        assert "0.993" in msg
        assert "WARN" in msg

    def test_format_message_critical(self):
        """Test message formatting for CRITICAL level."""
        alert = self._make_alert()
        msg = alert._format_message(AlertLevel.CRITICAL, "USDC", 0.98, 1.0, "binance")

        assert "USDC" in msg
        assert "CRITICAL" in msg
        assert "attention" in msg.lower()

    def test_format_message_above_peg(self):
        """Test message when price is above peg."""
        alert = self._make_alert()
        msg = alert._format_message(AlertLevel.WARN, "USDC", 1.007, 1.0, "coinbase")

        assert "↑" in msg

    def test_format_message_below_peg(self):
        """Test message when price is below peg."""
        alert = self._make_alert()
        msg = alert._format_message(AlertLevel.WARN, "USDC", 0.993, 1.0, "binance")

        assert "↓" in msg

    @pytest.mark.asyncio
    async def test_context_manager(self):
        """Test async context manager."""
        async with self._make_alert() as alert:
            pass
