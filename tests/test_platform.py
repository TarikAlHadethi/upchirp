"""Platform pieces that run without Docker: wire format, live images, run splitting, the API."""

import base64
import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("confluent_kafka")

from fastapi.testclient import TestClient

from upchirp import services, stream
from upchirp.api.app import create_app
from upchirp.config import ChirpConfig
from upchirp.frame import Frame, from_wire, to_wire
from upchirp.recording import record_simulation
from upchirp.replay import process_session
from upchirp.sim.engine import Simulator
from upchirp.sim.scene import default_scene


def _frames(n: int, session: str = "s") -> list[Frame]:
    scene = default_scene().model_copy(update={"duration_s": 0.1 * n})
    return [f for f, _ in Simulator(scene, session_id=session, start_ns=0).run()]


def test_wire_round_trip() -> None:
    frame = _frames(1)[0].model_copy(update={"meta": {"note": "hello", "n": 3}})
    assert from_wire(to_wire(frame)) == frame


def test_wire_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        from_wire(b"nope" + bytes(20))


def test_rdmap_message_is_8_bit_and_sized() -> None:
    power = np.full((64, 256), 1.0)
    power[32, 20] = 1e6  # +60 dB over the floor
    msg = services.rdmap_message(power, ChirpConfig())
    img = np.frombuffer(base64.b64decode(msg["data"]), dtype=np.uint8).reshape(msg["shape"])
    assert img[32, 20] == 255 and img[0, 0] == 0
    assert len(msg["data"]) < 30_000


class _FakeProducer:
    def __init__(self) -> None:
        self.sent: list[tuple[str, dict[str, Any]]] = []

    def produce(self, topic: str, value: bytes, key: bytes | None = None) -> None:
        self.sent.append((topic, json.loads(value)))

    def poll(self, _: float) -> None:
        pass

    def flush(self, _: float = 0) -> None:
        pass


def test_processor_starts_a_new_run_on_replay_loop() -> None:
    proc = services.Processor()
    proc.prod = _FakeProducer()  # type: ignore[assignment]
    frames = _frames(5)
    for f in frames + frames:  # the same recording twice, like a looping replay
        proc.handle(f)
    runs = [m["run_id"] for t, m in proc.prod.sent if t.endswith("tracks")]  # type: ignore[attr-defined]
    assert len(runs) == 10 and len(set(runs[:5])) == 1 and runs[4] != runs[5]
    topics = {t for t, _ in proc.prod.sent}  # type: ignore[attr-defined]
    assert topics == {stream.topic(t) for t in ("detections", "tracks", "rdmaps")}


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.delenv("UPCHIRP_DATABASE_URL", raising=False)
    scene = default_scene().model_copy(update={"duration_s": 4.0})  # 2 s quiet, 2 s targets
    process_session(record_simulation(Simulator(scene, session_id="api", start_ns=0), tmp_path))
    return TestClient(create_app(tmp_path, live=False))


def test_api_reads(client: TestClient) -> None:
    assert client.get("/api/health").json()["ok"] is True
    assert client.get("/api/sessions").json()[0]["session_id"] == "api"
    assert client.get("/api/summary").json()["total_tracks"] == 4
    drones = client.get("/api/tracks", params={"label": "drone_like"}).json()
    assert drones["track_count"] == 1


def test_api_errors_are_clean(client: TestClient) -> None:
    assert client.get("/api/tracks", params={"label": "ufo"}).status_code == 400
    assert client.get("/api/summary", params={"session": "missing"}).status_code == 404
    assert client.post("/api/ask", json={"question": ""}).status_code == 422


def test_public_guard_limits() -> None:
    from upchirp.api.guard import Limited, PublicGuard

    g = PublicGuard(per_minute=2, per_day=3, daily_cap_usd=0.01)
    g.check("a")
    g.check("a")
    with pytest.raises(Limited) as e:
        g.check("a")
    assert e.value.status == 429
    g.check("b")
    g.record(1000, 100, 0.02)  # over the cap
    with pytest.raises(Limited) as e:
        g.check("c")
    assert e.value.status == 503


def test_public_api_refuses_approvals(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("UPCHIRP_DATABASE_URL", raising=False)
    app = TestClient(create_app(tmp_path, live=False, public=True))
    assert app.get("/api/health").json()["public"] is True
    assert app.post("/api/ask/x/decision", json={"approve": True}).status_code == 403
