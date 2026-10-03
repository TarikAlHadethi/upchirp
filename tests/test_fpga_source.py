"""FPGA UDP source (proposed packet layout, docs/fpga-link.md), tested with a fake FPGA."""

import threading
import time

import numpy as np

from upchirp.config import ArrayConfig, ChirpConfig
from upchirp.dsp.detect import Detector
from upchirp.sim.engine import Simulator
from upchirp.sim.scene import get_scene
from upchirp.sources.fpga import (
    HEADER,
    MAX_SAMPLES_PER_PACKET,
    FpgaSource,
    Reassembler,
    decode_packet,
    encode_packets,
    send_frames,
)

CHIRP = ChirpConfig()


def _cube(seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    shape = (2, CHIRP.n_chirps, CHIRP.n_samples)
    return (0.3 * (rng.standard_normal(shape) + 1j * rng.standard_normal(shape))).astype(
        np.complex64)


def test_packets_fit_a_standard_ethernet_frame() -> None:
    packets = encode_packets(_cube(), 0)
    assert max(len(p) for p in packets) <= 1472
    assert len(packets) == 2 * CHIRP.n_chirps  # 256 samples fit in one packet per chirp
    p = decode_packet(packets[0])
    assert (p.rx, p.chirp, p.offset, len(p.samples)) == (0, 0, 0, CHIRP.n_samples)


def test_round_trip_in_any_order() -> None:
    cube = _cube() / 2  # well inside full scale, so nothing clips
    packets = encode_packets(cube, 7, max_samples=100)  # long chirps split over packets
    np.random.default_rng(1).shuffle(packets)
    r = Reassembler("s", CHIRP)
    frames = [f for f in (r.feed(p, received_ns=5) for p in packets) if f is not None]
    assert len(frames) == 1
    f = frames[0]
    assert (f.source, f.stage, f.n_rx, f.timestamp_ns) == ("fpga", "raw", 2, 5)
    assert f.meta["fpga_frame_counter"] == 7
    assert np.abs(f.cube() - cube).max() < 2 / 32768  # int16 quantization only


def test_frame_with_a_lost_packet_is_dropped() -> None:
    r = Reassembler("s", CHIRP)
    first = encode_packets(_cube(0), 0)
    del first[10]
    out = [r.feed(p) for p in first + encode_packets(_cube(1), 1)]
    frames = [f for f in out if f is not None]
    assert len(frames) == 1 and frames[0].meta["fpga_frame_counter"] == 1
    assert r.frames_dropped == 1
    assert frames[0].frame_index == 0  # frame indexes stay continuous for the pipeline


def test_bad_and_duplicate_packets_are_ignored() -> None:
    r = Reassembler("s", CHIRP)
    packets = encode_packets(_cube(), 0)
    assert r.feed(b"junk") is None
    assert r.feed(packets[0][:-4]) is None  # truncated
    wrong = encode_packets(np.zeros((1, 8, 32), np.complex64), 0)[0]  # other chirp config
    assert r.feed(wrong) is None
    assert r.bad_packets == 3
    out = [r.feed(p) for p in [packets[0], *packets]]  # first packet twice
    assert sum(f is not None for f in out) == 1


def test_header_is_32_bytes_little_endian() -> None:
    packet = encode_packets(_cube(), 0x01020304)[0]
    assert HEADER.size == 32 and packet[:4] == b"UPC0"
    assert packet[8:12] == bytes([4, 3, 2, 1])
    assert MAX_SAMPLES_PER_PACKET == 360


def test_fake_fpga_over_udp_gives_frames_the_detector_can_use() -> None:
    sim = Simulator(get_scene("default"), session_id="fpga", start_ns=0, seed=0)
    sent = [f for f, _ in zip((f for f, _ in sim.run()), range(30), strict=False)]
    src = FpgaSource("fpga-test", CHIRP, host="127.0.0.1", port=49917, idle_timeout_s=2.0)
    received = []

    def listen() -> None:
        received.extend(src.frames())

    t = threading.Thread(target=listen)
    t.start()
    time.sleep(0.3)  # let the listener bind
    send_frames(iter(sent), port=49917, realtime=True, frame_period_s=0.02)
    t.join()
    assert len(received) >= 28  # loopback UDP can, rarely, lose a packet
    det = Detector(CHIRP, ArrayConfig())
    found = [det.detect(f) for f in received]
    assert sum(len(d) > 0 for d in found[20:]) >= len(found[20:]) - 1
