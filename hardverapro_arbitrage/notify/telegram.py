from __future__ import annotations

import logging

import requests

from ..models import Deal
from .console import format_deal

logger = logging.getLogger(__name__)

_API_URL = "https://api.telegram.org/bot{token}/sendMessage"


class TelegramNotifier:
    """Sends a plain-text message per deal via a Telegram bot.

    Set up: message @BotFather to create a bot and get HA_TELEGRAM_BOT_TOKEN,
    then message your bot once and fetch HA_TELEGRAM_CHAT_ID from
    https://api.telegram.org/bot<token>/getUpdates.
    """

    def __init__(self, bot_token: str, chat_id: str, timeout_seconds: float = 10.0):
        self._url = _API_URL.format(token=bot_token)
        self._chat_id = chat_id
        self._timeout = timeout_seconds

    def notify(self, deal: Deal) -> None:
        try:
            response = requests.post(
                self._url,
                json={"chat_id": self._chat_id, "text": format_deal(deal)},
                timeout=self._timeout,
            )
            if response.status_code != 200:
                logger.error("Telegram notify failed: HTTP %s %s", response.status_code, response.text)
        except requests.RequestException:
            logger.exception("Telegram notify failed")
