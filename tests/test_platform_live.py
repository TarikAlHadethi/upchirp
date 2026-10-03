"""End to end through Redpanda and PostgreSQL. Skips unless the compose stack is up."""

import socket
import threading
import time
import uuid
from pathlib import Path

import pytest

pytest.importorskip("confluent_kafka")
pytest.importorskip("psycopg")

from upchirp import services, store, stream
from upchirp.agent import data
from upchirp.sim.engine import Simulator
from upchirp.sim.scene import default_scene

DB = "postgresql://upchirp:upchirp-dev-only@127.0.0.1:5433/upchirp"


def _port_open(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


pytestmark = pytest.mark.skipif(not (_port_open(19092) and _port_open(5433)),
                                reason="compose stack not running (make up)")


def test_source_to_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UPCHIRP_DATABASE_URL", DB)
    monkeypatch.setenv("UPCHIRP_TOPIC_PREFIX", f"test-{uuid.uuid4().hex[:6]}.")
    stream.ensure_topics()
    session = f"it-{uuid.uuid4().hex[:6]}"
    scene = default_scene().model_copy(update={"duration_s": 4.0})  # 2 s quiet start
    frames = [f for f, _ in Simulator(scene, session_id=session, start_ns=time.time_ns()).run()]

    workers = [threading.Thread(target=fn, kwargs={"max_idle_s": 6})
               for fn in (services.run_processor, services.run_writer)]
    for w in workers:
        w.start()
    time.sleep(4)  # consumers join their groups and start at the newest offset
    assert services.run_source(frames) == 40
    for w in workers:
        w.join(timeout=60)

    with store.connect() as conn:
        run = store.resolve_run(conn, session)
        assert run["frames"] == 40
        states = store.load_track_states(conn, run["run_id"])
    assert {s.label for s in states} >= {"person", "car", "drone_like"}
    summary = data.session_summary(tmp_path, session)
    assert summary["total_tracks"] == 4
