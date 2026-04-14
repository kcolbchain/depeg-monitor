"""Telegram alert channel via Bot API.

Sends depeg alerts to a Telegram chat via bot token.
Configure via config:
    alerts:
      telegram_bot_token: "123456:ABC-DEF..."
      telegram_chat_id: "-100123456789"
"""

from __future__ import annotations

import logging
from urllib.parse import quote

import aiohttp

from .base import Alert, AlertLevel

logger = logging.getLogger("depeg-monitor")


class TelegramAlert(Alert):
    """Send alerts to a Telegram chat via Bot API.

    Setup:
        1. Create a bot via @BotFather, get the token
        2. Get the chat_id (group: add bot, get updates; user: message bot, get updates)
        3. Add token and chat_id to config

    Config example:
        alerts:
          telegram_bot_token: "123456:ABC-DEF..."
          telegram_chat_id: "-100123456789"
    """

    API_BASE = "https://api.telegram.org/bot{token}/sendMessage"

    def __init__(self, bot_token: str, chat_id: str):
        self._token = bot_token
        self._chat_id = chat_id
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    def _format_message(self, level: AlertLevel, symbol: str, price: float, peg: float, source: str) -> str:
        """Format the alert as a Telegram message with emoji and formatting."""
        deviation = abs(price - peg) / peg * 100

        # Emoji based on level
        emoji = {
            AlertLevel.INFO: "ℹ️",
            AlertLevel.WARN: "⚠️",
            AlertLevel.CRITICAL: "🚨",
        }.get(level, "📊")

        # Color indication (Telegram doesn't support colors, but we use visual markers)
        marker = "█" if level == AlertLevel.CRITICAL else "▌" if level == AlertLevel.WARN else ""

        # Direction arrow
        direction = "↓" if price < peg else "↑" if price > peg else "="

        # Format price based on deviation (more decimals for small deviations)
        if deviation < 0.01:
            price_str = f"${price:.8f}"
        elif deviation < 1:
            price_str = f"${price:.6f}"
        else:
            price_str = f"${price:.4f}"

        lines = [
            f"{marker} {emoji} *{level.value.upper()}*: {symbol} Depeg Alert",
            "",
            f"📊 *Price*: {price_str} {direction}",
            f"🎯 *Peg*: ${peg:.4f}",
            f"📉 *Deviation*: {deviation:.3f}%",
            f"📡 *Source*: `{source}`",
        ]

        if level == AlertLevel.CRITICAL:
            lines.append("")
            lines.append("⚠️ _Immediate attention recommended_")

        return "\n".join(lines)

    async def send(
        self, level: AlertLevel, symbol: str, price: float, peg: float, source: str
    ) -> None:
        """Send the alert to Telegram."""
        text = self._format_message(level, symbol, price, peg, source)
        url = self.API_BASE.format(token=self._token)

        payload = {
            "chat_id": self._chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }

        # For critical alerts, also disable notification sound if supported
        if level == AlertLevel.CRITICAL:
            # Critical alerts should be noisy - don't disable_notification
            pass

        session = await self._get_session()

        try:
            async with session.post(url, json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("ok"):
                        logger.info(f"Telegram alert sent: {level.value} {symbol}")
                    else:
                        logger.warning(f"Telegram API error: {data.get('description', 'unknown')}")
                elif resp.status == 401:
                    logger.error("Telegram: Invalid bot token")
                elif resp.status == 403:
                    logger.error("Telegram: Bot not in chat or chat_id invalid")
                elif resp.status == 429:
                    # Rate limited - back off
                    retry_after = resp.headers.get("Retry-After", "30")
                    logger.warning(f"Telegram rate limited, retry after {retry_after}s")
                else:
                    logger.warning(f"Telegram returned {resp.status}")

        except aiohttp.ClientError as e:
            logger.warning(f"Telegram connection error: {e}")
        except Exception as e:
            logger.error(f"Telegram unexpected error: {e}")

    async def close(self) -> None:
        """Close the HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()

    async def __aenter__(self) -> "TelegramAlert":
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()
