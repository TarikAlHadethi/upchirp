"""Alerts: tell a person when a drone-like target appears ("alongside" item in the plan).

Reads the tracks topic. The first time a confirmed track in a run carries the
label drone_like, one message goes out; the same track never alerts twice.

Where messages go, by environment:
    TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID   Telegram bot
    SLACK_WEBHOOK_URL                         Slack incoming webhook
    neither                                   the log only (also the offline default)

A failed send is logged and never stops the service. Tokens come from the
environment (.env, git-ignored), never from the repo.
"""

import json
import logging
import os
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx

from upchirp import stream

log = logging.getLogger("upchirp.alerts")
Send = Callable[[str], None]


def _safe(e: Exception) -> str:
    """What went wrong, without the URL: Telegram's holds the bot token, Slack's is secret."""
    if isinstance(e, httpx.HTTPStatusError):
        return f"HTTP {e.response.status_code}"
    return type(e).__name__


def telegram_sender(token: str, chat_id: str) -> Send:
    def send(text: str) -> None:
        httpx.post(f"https://api.telegram.org/bot{token}/sendMessage", timeout=10,
                   json={"chat_id": chat_id, "text": text}).raise_for_status()
    return send


def slack_sender(url: str) -> Send:
    def send(text: str) -> None:
        httpx.post(url, json={"text": text}, timeout=10).raise_for_status()
    return send


def sender_from_env() -> tuple[str, Send]:
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if token and chat:
        return "telegram", telegram_sender(token, chat)
    if url := os.environ.get("SLACK_WEBHOOK_URL"):
        return "slack", slack_sender(url)
    return "log", lambda text: log.warning("ALERT %s", text)


def describe(track: dict[str, Any], timestamp_ns: int) -> str:
    when = datetime.fromtimestamp(timestamp_ns / 1e9, UTC).strftime("%H:%M:%S UTC")
    az = track["azimuth_deg"]
    side = "ahead" if abs(az) < 3 else f"{abs(az):.0f}° {'right' if az > 0 else 'left'}"
    return (f"Drone-like target: track {track['track_id']}, {track['range_m']:.0f} m away, "
            f"{side}, moving {track['speed_mps']:.1f} m/s, at {when}. "
            "Label from simple rules; check the live view.")


class AlertWatcher:
    """Decides which track messages deserve an alert. Kept separate from Kafka for tests."""

    def __init__(self, send: Send) -> None:
        self.send = send
        self.alerted: set[tuple[str, int]] = set()

    def handle(self, msg: dict[str, Any]) -> list[str]:
        sent = []
        for track in msg.get("tracks", []):
            key = (msg["run_id"], track["track_id"])
            if not track["confirmed"] or track["label"] != "drone_like" or key in self.alerted:
                continue
            self.alerted.add(key)
            text = describe(track, msg["timestamp_ns"])
            try:
                self.send(text)
                sent.append(text)
            except Exception as e:  # never let a flaky network stop the watcher
                log.error("alert not sent: %s", _safe(e))
        return sent


def run_alerts() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # it logs each URL, token included
    stream.ensure_topics()
    channel, send = sender_from_env()
    log.info("alerts go to: %s", channel)
    watcher = AlertWatcher(send)
    cons = stream.consumer("upchirp-alerts", [stream.TRACKS])
    try:
        for item in stream.messages(cons):
            if item is not None:
                watcher.handle(json.loads(item[1]))
    finally:
        cons.close()
