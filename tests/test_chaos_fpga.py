"""Chaos test for the FPGA packet reassembler and the two wire formats.

Rules:
- a frame that comes out is exactly one sent frame: no holes, nothing from another frame
- one frame counter gives at most one frame (a whole frame sent twice still gives two:
  an expected failure at the end of this file); frame indexes go 0, 1, 2, ...
- at most `max_open` frames are open, and packet memory covers open frames only
- bad, duplicate, late and overlapping packets never raise
- damaged frame messages and packets raise ValueError and nothing else
"""

import random

import numpy as np
import numpy.typing as npt
import pytest
from chaos_support import Step, check, seeds

from upchirp.config import ChirpConfig
from upchirp.frame import Frame, from_wire, to_wire
from upchirp.sources.fpga import Reassembler, decode_packet, encode_packets

TINY = ChirpConfig(id="tiny", n_chirps=2, n_samples=8)
N_RX = 2
SPLITS = (4, 3)  # samples per packet; the second split overlaps the first


def _cube(epoch: int, counter: int) -> npt.NDArray[np.complex64]:
    """What the fake FPGA sends for one frame: fixed by (epoch, counter), never all zero."""
    rng = np.random.default_rng([epoch, counter])
    shape = (N_RX, TINY.n_chirps, TINY.n_samples)
    cube = 0.4 * (rng.uniform(0.1, 1, shape) + 1j * rng.uniform(0.1, 1, shape))
    return cube.astype(np.complex64)


def _packets(epoch: int, counter: int, split: int) -> list[bytes]:
    return encode_packets(_cube(epoch, counter), counter, max_samples=SPLITS[split])


class FpgaWorld:
    def __init__(self) -> None:
        self.r = Reassembler("chaos", TINY)
        self.frames: list[Frame] = []
        self.sent: set[tuple[int, int]] = set()  # (epoch, counter) with a packet sent
        self.handed_out: list[tuple[int, int]] = []  # (epoch, counter) of each frame out
        self.problems: list[str] = []

    def apply(self, step: Step) -> None:
        name, args = step
        before = self.r.frames_out
        if name == "send":
            epoch, counter, split, index = args
            packets = _packets(epoch, counter, split)
            buf = packets[index % len(packets)]
            self.sent.add((epoch, counter & 0xFFFFFFFF))
        elif name == "cut":
            epoch, counter, index, keep = args
            packets = _packets(epoch, counter, 0)
            buf = packets[index % len(packets)][:keep]
        elif name == "other_config":
            buf = encode_packets(np.zeros((N_RX, 4, 16), np.complex64), args[0])[0]
        elif name == "other_channels":
            buf = encode_packets(np.zeros((4, TINY.n_chirps, TINY.n_samples), np.complex64),
                                 args[0])[-1]
        else:
            buf = bytes.fromhex(args[0])
        frame = self.r.feed(buf, received_ns=1)
        if (frame is not None) != (self.r.frames_out == before + 1):
            self.problems.append("frames_out does not match the frames handed out")
        if frame is not None:
            self.frames.append(frame)
            counter = frame.meta["fpga_frame_counter"]
            matches = [e for e, c in self.sent if c == counter
                       and np.abs(frame.cube() - _cube(e, c)).max() < 2 / 32768]
            if not matches:
                self.problems.append(f"frame for counter {counter} is not one sent frame")
            elif (matches[0], counter) in self.handed_out:
                self.problems.append(f"counter {counter} gave two frames")
            else:
                self.handed_out.append((matches[0], counter))

    def broken(self) -> list[str]:
        out = list(self.problems)
        r = self.r
        if len(r._open) > r.max_open:
            out.append(f"{len(r._open)} frames open, limit {r.max_open}")
        if any(key[0] not in r._open for key in r._seen):
            out.append("packet memory holds a frame that is no longer open")
        if [f.frame_index for f in self.frames] != list(range(len(self.frames))):
            out.append("frame indexes are not 0, 1, 2, ...")
        return out


def _steps(seed: int, n_frames: int = 25) -> list[Step]:
    """A fake FPGA with a careless network: packets shuffled, lost, repeated, resent with
    another split, and mixed with junk. The counter sometimes restarts from 0.

    Left out, because a frame is known by its counter alone and the packet layout cannot
    tell two boots apart (logged in the chaos report, not fixed): a restart while frames
    with small counters are still open, a packet that arrives on the other side of a
    restart, and the wrap of the counter at 32 bits."""
    rng = random.Random(seed)
    steps: list[Step] = []
    epoch, counter = 0, 0
    boot = 0  # where the newest boot's packets start
    for _ in range(n_frames):
        split = rng.randrange(2)
        n = len(_packets(epoch, counter, split))
        mine: list[Step] = [("send", (epoch, counter, split, i)) for i in range(n)]
        rng.shuffle(mine)
        if rng.random() < 0.25:
            mine.pop()  # a lost packet
        for _ in range(rng.randrange(3)):
            mine.insert(rng.randrange(len(mine) + 1),
                        ("send", (epoch, counter, rng.randrange(2), rng.randrange(8))))
        extras: list[Step] = [
            ("cut", (epoch, counter, rng.randrange(8), rng.randrange(40))),
            ("junk", (rng.randbytes(rng.randrange(50)).hex(),)),
            ("other_config", (counter,)),
            ("other_channels", (counter,)),
            ("send", (epoch, max(counter - rng.randrange(1, 4), 0), 0, rng.randrange(8))),  # late
        ]
        for extra in rng.sample(extras, rng.randrange(3)):
            mine.insert(rng.randrange(len(mine) + 1), extra)
        # packets land a few places early or late, so the frames around this one overlap
        for step in mine:
            steps.insert(rng.randrange(max(len(steps) - 3, boot), len(steps) + 1), step)
        counter += rng.choice([1, 1, 1, 2])
        if counter > 8 and rng.random() < 0.2:
            epoch, counter, boot = epoch + 1, 0, len(steps)
    return steps


@pytest.mark.parametrize("seed", seeds())
def test_reassembler_keeps_its_rules_under_chaos(seed: int) -> None:
    check(FpgaWorld, _steps(seed), seed)


@pytest.mark.parametrize("seed", seeds())
def test_damaged_wire_messages_raise_value_error_only(seed: int) -> None:
    rng = random.Random(seed)
    frame = Frame.from_cube(_cube(0, seed), source="fpga", session_id="s", frame_index=seed,
                            timestamp_ns=5, chirp_config_id=TINY.id, stage="raw",
                            meta={"note": "x"})
    wire = to_wire(frame)
    assert from_wire(wire) == frame
    packet = _packets(0, seed, 0)[0]
    for _ in range(200):
        for good, read in ((wire, from_wire), (packet, decode_packet)):
            buf = bytearray(good)
            kind = rng.randrange(4)
            if kind == 0:  # flip a few bytes, mostly in the header
                for _ in range(rng.randrange(1, 4)):
                    buf[rng.randrange(min(len(buf), 120))] = rng.randrange(256)
            elif kind == 1:
                del buf[rng.randrange(len(buf)):]
            elif kind == 2:
                buf += rng.randbytes(rng.randrange(1, 9))
            else:
                buf = bytearray(rng.randbytes(rng.randrange(60)))
            try:
                read(bytes(buf))
            except ValueError:
                pass  # the only refusal the stream services skip


@pytest.mark.xfail(strict=True, reason=(
    "Known limit, not fixed on purpose: once a frame is handed out the reassembler forgets "
    "its counter, so a whole frame that arrives a second time (with no newer frame open) "
    "comes out again. Remembering finished counters interacts with the restart rule, where "
    "the counter starts from 0 again. To be settled with the FPGA packet layout "
    "(docs/fpga-link.md), for example with a boot id in the header."))
def test_saved_sequence_whole_frame_sent_twice_gives_one_frame() -> None:
    once: list[Step] = [("send", (0, 0, 0, i)) for i in range(len(_packets(0, 0, 0)))]
    check(FpgaWorld, once + once)
