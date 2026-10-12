from pathlib import Path

import pytest
from typer.testing import CliRunner

from upchirp.cli import app
from upchirp.recording import (
    FRAMES_FILE,
    read_frames,
    read_ground_truth,
    read_manifest,
    record_simulation,
    resolve_session,
)
from upchirp.sim.engine import Simulator
from upchirp.sim.scene import default_scene
from upchirp.sources.replay import ReplaySource
from upchirp.sources.sim import SimSource


def _short_sim(session_id: str = "s1") -> Simulator:
    scene = default_scene().model_copy(update={"duration_s": 0.5})
    return Simulator(scene, session_id=session_id, start_ns=1_000, seed=3)


def test_replay_matches_simulation(tmp_path: Path) -> None:
    session_dir = record_simulation(_short_sim(), tmp_path)
    original = list(SimSource(_short_sim()).frames())
    replayed = list(ReplaySource(session_dir).frames())

    assert len(replayed) == len(original) == 5
    for a, b in zip(original, replayed, strict=True):
        assert b.source == "replay"
        assert b.model_copy(update={"source": "sim"}) == a


def test_ground_truth_saved(tmp_path: Path) -> None:
    session_dir = record_simulation(_short_sim(), tmp_path)
    truth = read_ground_truth(session_dir)
    assert len(truth) == 5 * 4
    assert {t.label for t in truth} == {"person", "car", "drone_like"}
    manifest = read_manifest(session_dir)
    assert manifest["n_frames"] == 5
    assert manifest["scene"]["name"] == "default"


def test_resolve_latest_and_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        resolve_session(tmp_path, "latest")
    record_simulation(_short_sim("a"), tmp_path)
    second = record_simulation(_short_sim("b"), tmp_path)
    assert resolve_session(tmp_path, "latest") == second
    assert resolve_session(tmp_path, "a").name == "a"
    with pytest.raises(FileNotFoundError):
        resolve_session(tmp_path, "nope")


def test_cli_sim_then_replay(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["sim", "--data-dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "Saved 120 frames and 480 ground truth rows" in result.output

    result = runner.invoke(app, ["replay", "--data-dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "Replayed 120 frames" in result.output

    session_dir = resolve_session(tmp_path, "latest")
    assert sum(1 for _ in read_frames(session_dir / FRAMES_FILE)) == 120


def test_cli_unknown_scene(tmp_path: Path) -> None:
    result = CliRunner().invoke(app, ["sim", "--scene", "mars", "--data-dir", str(tmp_path)])
    assert result.exit_code != 0


def test_source_explains_a_missing_recording_or_scene(tmp_path: Path,
                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("confluent_kafka")
    from upchirp import stream

    monkeypatch.setattr(stream, "ensure_topics", lambda: None)  # no broker needed to say no
    result = CliRunner().invoke(app, ["source", "--session", "nope", "--data-dir", str(tmp_path)])
    assert result.exit_code == 1 and isinstance(result.exception, SystemExit)
    assert "no session 'nope'" in result.output
    result = CliRunner().invoke(app, ["source", "--scene", "mars"])
    assert result.exit_code == 2 and "unknown scene" in result.output


def test_vectors_explains_a_frame_past_the_end(tmp_path: Path) -> None:
    result = CliRunner().invoke(app, ["vectors", "--frame", "5000", "--out", str(tmp_path)])
    assert result.exit_code == 2 and "120 frames" in result.output


def test_vectors_refuses_a_negative_frame(tmp_path: Path) -> None:
    result = CliRunner().invoke(app, ["vectors", "--frame", "-1", "--out", str(tmp_path)])
    assert result.exit_code == 2 and "--frame" in result.output
    assert not any(tmp_path.iterdir())  # nothing written
