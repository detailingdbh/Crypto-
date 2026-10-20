"""Optional Telegram notifications. Failures are logged, never raised."""

from __future__ import annotations

import json
import logging
import urllib.request

log = logging.getLogger(__name__)


class Notifier:
    def __init__(self, token: str = "", chat_id: str = ""):
        self.token = token
        self.chat_id = chat_id

    def send(self, text: str) -> None:
        log.info("NOTIF: %s", text)
        if not (self.token and self.chat_id):
            return
        body = json.dumps({"chat_id": self.chat_id, "text": text}).encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{self.token}/sendMessage",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        try:
            urllib.request.urlopen(req, timeout=10).close()
        except Exception as e:
            log.warning("échec de la notification Telegram : %s", e)
