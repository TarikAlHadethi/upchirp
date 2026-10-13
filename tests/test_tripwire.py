"""Tripwires: runtime checks of always-true rules. They report and never raise."""

import numpy as np
import pytest

from upchirp import tripwire
from upchirp.config import ChirpConfig
from upchirp.dsp.detect import Detection
from upchirp.dsp.tracker import Tracker
from upchirp.sources.fpga import Reassembler, encode_packets


@pytest.fixture(autouse=True)
def fresh(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tripwire, "COUNTS", {})
    monkeypatch.setattr(tripwire, "_last_logged", {})


def test_tripwire_logs_counts_and_never_raises(caplog: pytest.LogCaptureFixture) -> None:
    tripwire.tripped("some-rule", "3 of 4")
    tripwire.tripped("some-rule", "3 of 4")
    assert tripwire.COUNTS == {"some-rule": 2}
    assert caplog.text.count("TRIPWIRE some-rule: 3 of 4") == 1  # one line a minute per rule


def test_tripwire_counts_in_prometheus() -> None:
    metrics = pytest.importorskip("upchirp.metrics")
    before = metrics.TRIPWIRES.labels("counted-rule")._value.get()
    tripwire.tripped("counted-rule")
    assert metrics.TRIPWIRES.labels("counted-rule")._value.get() == before + 1


def test_tripwire_survives_a_broken_report(monkeypatch: pytest.MonkeyPatch,
                                           caplog: pytest.LogCaptureFixture) -> None:
    monkeypatch.setattr(tripwire, "COUNTS", None)  # makes the report itself fail
    tripwire.tripped("some-rule")
    assert "could not be reported" in caplog.text


def test_tracker_tripwires_fire_and_change_nothing() -> None:
    det = Detection(session_id="t", frame_index=0, timestamp_ns=0, range_m=20.0,
                    radial_velocity_mps=0.0, azimuth_deg=0.0, snr_db=30.0, range_bin=0,
                    doppler_bin=0)
    tracker = Tracker()
    tracker.step([det], 0)
    assert len(tracker.states("t", 0)) == 1 and tripwire.COUNTS == {}
    tracker._tracks.append(tracker._tracks[0])  # the same id twice: cannot happen
    tracker._tracks[0].x[0] = np.nan
    assert len(tracker.states("t", 0)) == 2  # still answers
    assert tripwire.COUNTS == {"tracker-unique-ids": 1, "tracker-finite-state": 1}


def test_fpga_tripwire_fires_on_a_frame_with_a_hole() -> None:
    chirp = ChirpConfig(id="tiny", n_chirps=2, n_samples=8)
    packets = encode_packets(np.full((1, 2, 8), 0.1, np.complex64), 0)
    r = Reassembler("s", chirp)
    assert r.feed(packets[0]) is None and tripwire.COUNTS == {}
    r._open[0].have[0, 0, 0] = False  # a cell loses its mark: cannot happen
    assert r.feed(packets[1]) is not None  # the frame still comes out, as before
    assert tripwire.COUNTS == {"fpga-frame-complete": 1}


def test_guard_tripwire_fires_on_a_release_with_nothing_held(
        monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("psycopg")
    from upchirp.api.guard import PublicGuard

    monkeypatch.delenv("UPCHIRP_DATABASE_URL", raising=False)
    guard = PublicGuard(daily_cap_usd=1.0, reserve_usd=0.10)
    guard.check("a")
    guard.record(1, 1, 0.01)
    assert tripwire.COUNTS == {}
    guard.record(1, 1, 0.01)  # recorded twice for one question
    assert tripwire.COUNTS == {"guard-release-without-hold": 1} and guard.reserved == 0.0
