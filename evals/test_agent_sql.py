"""Agent answers checked against SQL (step 5).

A simulated session goes through the pipeline into PostgreSQL. Expected answers
are plain SQL over the tracks table, written independently of the agent's tools.

- test_tools_match_sql: the tool layer agrees with SQL (no model needed).
- test_agent_matches_sql: the agent's answers agree with SQL (needs a model).

Both skip unless the database from compose.yaml is up.
"""

import asyncio
import socket
import time
import uuid
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("psycopg")

from upchirp import store
from upchirp.agent import data
from upchirp.agent.answers import numbers_in
from upchirp.agent.availability import model_available
from upchirp.recording import record_simulation
from upchirp.replay import process_session
from upchirp.sim.engine import Simulator
from upchirp.sim.scene import get_scene

DB = "postgresql://upchirp:upchirp-dev-only@127.0.0.1:5433/upchirp"


def _db_up() -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", 5433)) == 0


pytestmark = pytest.mark.skipif(not _db_up(), reason="database not running (make up)")

# Each track's label is its most common known label, as in the agent's tools.
TRACK_LABELS = """
    SELECT track_id, mode() WITHIN GROUP (ORDER BY label) AS label
    FROM tracks WHERE run_id = %(run)s AND confirmed AND label <> 'unknown'
    GROUP BY track_id
"""
SQL = {
    "people": f"SELECT count(*) AS v FROM ({TRACK_LABELS}) l WHERE label = 'person'",
    "car_max_speed": f"""SELECT max(t.speed_mps) AS v FROM tracks t
        JOIN ({TRACK_LABELS}) l USING (track_id)
        WHERE t.run_id = %(run)s AND t.confirmed AND l.label = 'car'""",
    "drone_closest": f"""SELECT min(t.range_m) AS v FROM tracks t
        JOIN ({TRACK_LABELS}) l USING (track_id)
        WHERE t.run_id = %(run)s AND t.confirmed AND l.label = 'drone_like'""",
}
QUESTIONS = {
    "people": ("How many people were tracked in the latest session?", 0.0),
    "car_max_speed": ("What was the highest speed of any car in the latest session, in m/s?",
                      0.15),
    "drone_closest": ("How close did the closest drone-like track get in the latest session?",
                      0.15),
}


@pytest.fixture(scope="module")
def loaded(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, str, dict[str, float]]:
    """Run the crossing scene through the pipeline and insert it as the newest run."""
    data_dir = tmp_path_factory.mktemp("sql")
    session_id = f"sql-{uuid.uuid4().hex[:6]}"
    sim = Simulator(get_scene("crossing"), session_id=session_id, start_ns=time.time_ns())
    session_dir = record_simulation(sim, data_dir)
    process_session(session_dir)
    from upchirp.dsp.tracker import TrackState
    from upchirp.recording import TRACKS_FILE, read_rows

    run_id = f"{session_id}#eval"
    rows = [s.__dict__ for s in read_rows(session_dir / TRACKS_FILE, TrackState) if s.confirmed]
    with store.connect_to(DB) as conn:
        store.init_schema(conn)
        store.insert_tracks(conn, run_id, rows)
        store.upsert_run(conn, run_id, session_id, "sim", rows[0]["timestamp_ns"], frames=0)
        store.upsert_run(conn, run_id, session_id, "sim", rows[-1]["timestamp_ns"],
                         frames=sim.scene.n_frames)
        expected = {k: float(conn.execute(q, {"run": run_id}).fetchone()["v"])  # type: ignore[index]
                    for k, q in SQL.items()}
    return data_dir, run_id, expected


def test_tools_match_sql(loaded: tuple[Path, str, dict[str, float]],
                         monkeypatch: pytest.MonkeyPatch) -> None:
    data_dir, run_id, expected = loaded
    monkeypatch.setenv("UPCHIRP_DATABASE_URL", DB)
    tracks = data.track_summaries(data_dir, run_id)["tracks"]
    people = [t for t in tracks if t["label"] == "person"]
    cars = [t for t in tracks if t["label"] == "car"]
    drones = [t for t in tracks if t["label"] == "drone_like"]
    print(f"\nSQL says {expected}")
    assert len(people) == expected["people"]
    assert max(t["max_speed_mps"] for t in cars) == pytest.approx(expected["car_max_speed"],
                                                                  abs=0.01)
    assert min(t["closest_range_m"] for t in drones) == pytest.approx(
        expected["drone_closest"], abs=0.01)


@pytest.mark.skipif(not model_available(), reason="no model reachable")
@pytest.mark.parametrize("key", list(QUESTIONS))
def test_agent_matches_sql(loaded: tuple[Path, str, dict[str, float]], key: str,
                           monkeypatch: pytest.MonkeyPatch) -> None:
    from upchirp.agent.graph import ask

    data_dir, _, expected = loaded
    monkeypatch.setenv("UPCHIRP_DATABASE_URL", DB)
    question, tol = QUESTIONS[key]

    def deny(_: list[Any]) -> bool:
        return False

    answer, _ = asyncio.run(ask(question, data_dir, approver=deny))
    print(f"\n{question}\n  SQL: {expected[key]:.2f}\n  agent: {answer}")
    assert any(abs(n - expected[key]) <= tol + 1e-9 for n in numbers_in(answer)), answer
