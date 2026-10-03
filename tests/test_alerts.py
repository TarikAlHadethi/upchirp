from typing import Any

import pytest

from upchirp import alerts


def _msg(run: str, tracks: list[dict[str, Any]]) -> dict[str, Any]:
    return {"run_id": run, "timestamp_ns": 1_800_000_000_000_000_000, "tracks": tracks}


def _track(tid: int, label: str, confirmed: bool = True, az: float = -15.0) -> dict[str, Any]:
    return {"track_id": tid, "label": label, "confirmed": confirmed, "range_m": 44.4,
            "azimuth_deg": az, "speed_mps": 0.4}


def test_one_alert_per_drone_track() -> None:
    sent: list[str] = []
    w = alerts.AlertWatcher(sent.append)
    w.handle(_msg("r1", [_track(1, "person"), _track(3, "drone_like", confirmed=False)]))
    assert sent == []
    w.handle(_msg("r1", [_track(3, "drone_like")]))
    w.handle(_msg("r1", [_track(3, "drone_like")]))
    w.handle(_msg("r2", [_track(3, "drone_like", az=0.5)]))  # a new run is a new track
    assert len(sent) == 2
    assert "track 3, 44 m away, 15° left" in sent[0] and "ahead" in sent[1]


def test_send_failure_does_not_stop_the_watcher() -> None:
    def broken(_: str) -> None:
        raise ConnectionError("offline")

    w = alerts.AlertWatcher(broken)
    assert w.handle(_msg("r1", [_track(3, "drone_like")])) == []
    assert ("r1", 3) in w.alerted  # not retried in a loop


def test_channel_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "SLACK_WEBHOOK_URL"):
        monkeypatch.delenv(var, raising=False)
    assert alerts.sender_from_env()[0] == "log"
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.example/x")
    assert alerts.sender_from_env()[0] == "slack"
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "c")
    assert alerts.sender_from_env()[0] == "telegram"


def test_bot_token_never_reaches_the_log(caplog: pytest.LogCaptureFixture) -> None:
    import httpx

    url = "https://api.telegram.org/botSECRET123:abc/sendMessage"

    def send(_: str) -> None:
        req = httpx.Request("POST", url)
        raise httpx.HTTPStatusError("Client error for url " + url, request=req,
                                    response=httpx.Response(401, request=req))

    alerts.AlertWatcher(send).handle(_msg("r1", [_track(1, "drone_like")]))
    assert "HTTP 401" in caplog.text and "SECRET123" not in caplog.text
