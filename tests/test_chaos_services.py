"""Chaos tests for the processor (with a fake producer) and the alert watcher.

Rules:
- a run holds one session and its frame numbers only go up; a run that ended never comes back
- every processed frame gives one detections and one tracks message with that frame's run id
- a frame the processor cannot use raises ValueError or KeyError, sends nothing and changes
  nothing, and the next good frame is processed
- messages hold no NaN
- one track in one run alerts at most once, and only when confirmed and drone_like
- unreadable messages and failed sends never stop the watcher, and never log a secret
- the watcher remembers a limited number of runs
"""

import json
import logging
import random
from typing import Any

import pytest
from chaos_support import Step, check, seeds

pytest.importorskip("confluent_kafka")

from upchirp import alerts, services, stream
from upchirp.frame import Frame
from upchirp.sim.engine import Simulator
from upchirp.sim.scene import default_scene

POOL: dict[str, list[Frame]] = {}
SECRET = "123456:not-a-real-token"


def _pool(session: str) -> list[Frame]:
    if session not in POOL:
        scene = default_scene().model_copy(update={"duration_s": 0.4})
        POOL[session] = [f for f, _ in Simulator(scene, session_id=session, start_ns=0).run()]
    return POOL[session]


def _no_nan(text: str) -> Any:
    raise ValueError(f"{text} in a message")


class _Producer:
    def __init__(self) -> None:
        self.sent: list[tuple[str, dict[str, Any]]] = []

    def produce(self, topic: str, value: bytes, key: bytes | None = None) -> None:
        self.sent.append((stream.base_topic(topic), json.loads(value, parse_constant=_no_nan)))

    def poll(self, _: float) -> None:
        pass


class ProcessorWorld:
    def __init__(self) -> None:
        self.proc = services.Processor()
        self.prod = _Producer()
        self.proc.prod = self.prod  # type: ignore[assignment]
        self.problems: list[str] = []

    def apply(self, step: Step) -> None:
        name, (session, index) = step
        frame = _pool(session)[index % 4].model_copy(update={"frame_index": index})
        if name == "unknown_config":
            frame = frame.model_copy(update={"chirp_config_id": "nope"})
        elif name == "one_channel":
            frame = Frame.from_cube(frame.cube()[:1], **frame.model_dump(
                exclude={"data", "n_rx", "n_chirps", "n_samples"}))
        sent = len(self.prod.sent)
        state = (self.proc.run_id, self.proc.session_id, self.proc.last_index)
        try:
            self.proc.handle(frame)
        except (ValueError, KeyError):  # what run_processor skips and counts
            if len(self.prod.sent) != sent:
                self.problems.append("a refused frame still sent messages")
            if (self.proc.run_id, self.proc.session_id, self.proc.last_index) != state:
                self.problems.append("a refused frame changed the run")
            return
        new = self.prod.sent[sent:]
        topics = sorted(t for t, _ in new)
        if topics not in (["detections", "rdmaps", "tracks"], ["detections", "tracks"]):
            self.problems.append(f"one frame sent {topics}")
        if any((m["run_id"], m["session_id"], m["frame_index"])
               != (self.proc.run_id, session, index) for _, m in new):
            self.problems.append("a message does not carry its frame's run, session and index")

    def broken(self) -> list[str]:
        out = list(self.problems)
        heads = [(m["run_id"], m["session_id"], m["frame_index"])
                 for t, m in self.prod.sent if t == "tracks"]
        ended: set[str] = set()
        for (run, session, index), (next_run, next_session, next_index) in zip(
                heads, heads[1:], strict=False):
            if next_run == run:
                if next_session != session or next_index <= index:
                    out.append(f"run {run} holds frame {next_index} after {index}")
            else:
                ended.add(run)
                if next_run in ended:
                    out.append(f"run {next_run} came back after it ended")
        for topic, m in self.prod.sent:
            if topic == "tracks" and len({t["track_id"] for t in m["tracks"]}) != len(m["tracks"]):
                out.append("two tracks in one message share an id")
        return out


def _processor_steps(seed: int, n: int = 14) -> list[Step]:
    rng = random.Random(seed)
    steps: list[Step] = []
    session, index = "a", 0
    for _ in range(n):
        kind = rng.choice(["next"] * 6 + ["same", "back", "other_session", "jump"])
        if kind == "next":
            index += 1
        elif kind == "back":
            index = rng.randrange(index + 1)
        elif kind == "jump":
            index += rng.randrange(2, 50)
        elif kind == "other_session":
            session, index = ("b" if session == "a" else "a"), rng.randrange(3)
        name = rng.choice(["frame"] * 8 + ["unknown_config", "one_channel"])
        at = index + rng.randrange(3) if name != "frame" else index
        steps.append((name, (session, at)))
    return steps


@pytest.mark.parametrize("seed", seeds())
def test_processor_keeps_its_rules_under_chaos(seed: int) -> None:
    check(ProcessorWorld, _processor_steps(seed), seed)


class _Records(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(record.getMessage())


class AlertWorld:
    def __init__(self) -> None:
        self.sends: list[str] = []
        self.fail = False
        self.watcher = alerts.AlertWatcher(self._send)
        self.may_alert: set[tuple[str, int]] = set()  # confirmed drone_like, seen in a message
        self.alerts: list[tuple[str, int]] = []  # (run, track) of every send, failed or not
        self.runs: list[str] = []
        self.log = _Records()
        self.problems: list[str] = []

    def _send(self, text: str) -> None:
        self.sends.append(text)
        if self.fail:
            raise ConnectionError(f"https://api.telegram.org/bot{SECRET}/sendMessage")

    def apply(self, step: Step) -> None:
        name, args = step
        logger = logging.getLogger("upchirp.alerts")
        logger.addHandler(self.log)
        try:
            if name == "raw":
                self.watcher.handle_raw(bytes.fromhex(args[0]))
                return
            run, self.fail, rows = args
            if run not in self.runs:
                self.runs.append(run)
            tracks = [{"track_id": i, "confirmed": c, "label": label, "range_m": 40.0,
                       "azimuth_deg": 5.0, "speed_mps": 1.0} for i, c, label in rows]
            for i, c, label in rows:
                if c and label == "drone_like":
                    self.may_alert.add((run, i))
            before = len(self.sends)
            msg = {"run_id": run, "timestamp_ns": 1_800_000_000_000_000_000, "tracks": tracks}
            self.watcher.handle_raw(json.dumps(msg).encode())
            for text in self.sends[before:]:
                ids = [i for i, c, label in rows if c and label == "drone_like"
                       and text.startswith(f"Drone-like target: track {i},")]
                if not ids:
                    self.problems.append("an alert went out for a track that should not alert")
                else:
                    self.alerts.append((run, ids[0]))
        finally:
            logger.removeHandler(self.log)

    def broken(self) -> list[str]:
        out = list(self.problems)
        if len(set(self.alerts)) != len(self.alerts):
            out.append("one track alerted twice in one run")
        if not self.watcher.alerted <= set(self.alerts):
            out.append("a track is marked alerted but no alert was tried")
        if any(SECRET in line for line in self.log.lines):
            out.append("a secret reached the log")
        if len({run for run, _ in self.watcher.alerted}) > alerts.REMEMBERED_RUNS:
            out.append("the watcher remembers more runs than its limit")
        return out


def _alert_steps(seed: int, n: int = 80) -> list[Step]:
    """A looping replay: runs follow each other, with a few late messages of the run before."""
    rng = random.Random(seed)
    steps: list[Step] = []
    run = 0
    for _ in range(n):
        if rng.random() < 0.25:
            run += 1
        if rng.random() < 0.1:
            junk = rng.choice([b"not json", b"[1]", b'{"tracks": [{"track_id": 1}]}',
                               b'{"run_id": "r0", "tracks": [3]}', rng.randbytes(8)])
            steps.append(("raw", (junk.hex(),)))
            continue
        name = f"r{run - 1 if run and rng.random() < 0.1 else run}"
        rows = [(rng.randrange(1, 5), rng.random() < 0.7,
                 rng.choice(["drone_like", "drone_like", "person", "car", "unknown"]))
                for _ in range(rng.randrange(4))]
        steps.append(("tracks", (name, rng.random() < 0.15, rows)))
    return steps


@pytest.mark.parametrize("seed", seeds())
def test_alert_watcher_keeps_its_rules_under_chaos(seed: int) -> None:
    check(AlertWorld, _alert_steps(seed), seed)
