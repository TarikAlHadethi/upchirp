from pathlib import Path

import pytest

from upchirp.agent import data
from upchirp.agent.answers import DroneTruth, check_drone_answer, drone_truth
from upchirp.recording import read_ground_truth, record_simulation
from upchirp.replay import process_session
from upchirp.sim.engine import Simulator
from upchirp.sim.scene import default_scene


@pytest.fixture(scope="module")
def processed(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    data_dir = tmp_path_factory.mktemp("agentdata")
    scene = default_scene().model_copy(update={"duration_s": 4.0})  # 2 s quiet start
    session_dir = record_simulation(Simulator(scene, session_id="s", start_ns=0), data_dir)
    process_session(session_dir)
    return data_dir, session_dir


def test_track_summaries(processed: tuple[Path, Path]) -> None:
    data_dir, _ = processed
    everything = data.track_summaries(data_dir)
    assert everything["track_count"] == 4
    assert {t["label"] for t in everything["tracks"]} == {"person", "car", "drone_like"}
    drones = data.track_summaries(data_dir, label="drone_like")
    assert drones["track_count"] == 1
    assert 50 < drones["tracks"][0]["closest_range_m"] < 65


def test_time_window(processed: tuple[Path, Path]) -> None:
    data_dir, _ = processed
    last = data.track_summaries(data_dir, last_minutes=0.5 / 60)  # last half second
    assert last["window"]["from_s"] == pytest.approx(last["window"]["to_s"] - 0.5, abs=0.11)
    for t in last["tracks"]:
        assert t["first_seen_s_after_start"] >= last["window"]["from_s"]


def test_unknown_label_rejected(processed: tuple[Path, Path]) -> None:
    with pytest.raises(ValueError):
        data.track_summaries(processed[0], label="ufo")


def test_unprocessed_session_says_so(tmp_path: Path) -> None:
    scene = default_scene().model_copy(update={"duration_s": 0.2})
    record_simulation(Simulator(scene, session_id="raw", start_ns=0), tmp_path)
    with pytest.raises(FileNotFoundError, match="replay it first"):
        data.track_summaries(tmp_path)
    assert data.list_sessions(tmp_path)[0]["processed"] is False


def test_search_docs_finds_decisions() -> None:
    docs = Path(__file__).resolve().parents[1] / "docs"
    hits = data.search_docs(docs, "Redpanda Kafka")
    assert hits and hits[0]["doc"].startswith("decisions/")


def test_drone_truth_and_checker(processed: tuple[Path, Path]) -> None:
    expected = drone_truth(read_ground_truth(processed[1]))
    assert expected.count == 1 and expected.closest_range_m is not None
    r = expected.closest_range_m
    assert check_drone_answer(f"One drone-like track; closest {r:.1f} m.", expected).ok
    assert not check_drone_answer(f"Two drone-like tracks; closest {r:.1f} m.", expected).ok
    assert not check_drone_answer(f"1 drone-like track, closest {r + 25:.1f} m.", expected).ok


def test_checker_with_no_drones() -> None:
    none = DroneTruth(count=0, closest_range_m=None)
    assert check_drone_answer("No drone-like tracks were seen.", none).ok
    assert not check_drone_answer("There was 1 drone-like track.", none).ok


def test_stitch_joins_broken_pieces_only() -> None:
    from upchirp.dsp.tracker import TrackState

    def piece(tid: int, t0: float, t1: float, x0: float, label: str = "drone_like"
              ) -> list[TrackState]:
        out = []
        for k in range(int((t1 - t0) * 10) + 1):
            t = t0 + k * 0.1
            x = x0 + 2.0 * (t - t0)
            out.append(TrackState("s", k, int(t * 1e9), tid, True, x, 40.0, 2.0, 0.0,
                                  40.0, 0.0, 0.0, 2.0, 5, 0, label, -20.0))
        return out

    tracks = {4: piece(4, 0, 5, 0.0),          # ends at x=10 at t=5
              7: piece(7, 6, 9, 12.0),         # starts 1 s later where 4 was heading
              8: piece(8, 6, 9, -30.0),        # same time but far away: another object
              9: piece(9, 6.5, 9, 13.0, "car")}  # right place, wrong label
    objects = data.stitch(tracks)
    assert objects[4] == [4, 7]
    assert objects[8] == [8] and objects[9] == [9]


def test_stitch_joins_pieces_of_a_hovering_target() -> None:
    """Short pieces of a hovering drone carry wild velocity estimates; they still join."""
    from upchirp.dsp.tracker import TrackState

    def piece(tid: int, t0: float, vx: float) -> list[TrackState]:
        return [TrackState("s", k, int((t0 + k * 0.1) * 1e9), tid, True, 5.0, 58.0, vx, 0.0,
                           58.2, 4.9, 0.0, abs(vx), 5, 0, "drone_like", -29.0)
                for k in range(5)]

    tracks = {1: piece(1, 0.0, 6.0), 2: piece(2, 1.0, -5.0), 3: piece(3, 2.0, 4.0)}
    assert data.stitch(tracks) == {1: [1, 2, 3]}


def test_stitch_still_object_over_a_longer_gap_only() -> None:
    """A hovering drone lost for 7 s is one object; a walker passing the same spot is not."""
    from upchirp.dsp.tracker import TrackState

    def piece(tid: int, t0: float, t1: float, x0: float, vx: float,
              label: str = "drone_like") -> list[TrackState]:
        return [TrackState("s", k, int((t0 + k * 0.1) * 1e9), tid, True,
                           x0 + vx * k * 0.1, 50.0, vx, 0.0, 50.0, 0.0, 0.0, abs(vx), 5, 0,
                           label, -25.0) for k in range(int((t1 - t0) * 10) + 1)]

    hover = {1: piece(1, 0, 4, 5.0, 0.0), 2: piece(2, 11, 15, 6.0, 0.0)}
    assert data.stitch(hover) == {1: [1, 2]}
    walkers = {1: piece(1, 0, 4, 0.0, 1.4, "person"), 2: piece(2, 11, 15, 6.5, 1.4, "person")}
    assert data.stitch(walkers) == {1: [1], 2: [2]}
