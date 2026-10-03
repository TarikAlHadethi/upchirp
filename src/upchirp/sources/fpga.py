"""FPGA source: frames from Abdullah's FPGA over UDP (step 10, his weeks 12 to 16).

The packet layout is a proposal (docs/fpga-link.md), to agree with Abdullah and
record in a decision record. Everything that depends on it is in this file:
`HEADER`, `encode_packets` (what the FPGA sends) and `Reassembler` (what we do
with it). The rest of the pipeline only sees the usual Frame message.

One packet carries part of one chirp of one receive channel: a 32-byte header,
then int16 I and Q samples interleaved, all little-endian. A frame is complete
when every sample of every chirp of every channel has arrived. Packets can
arrive in any order; a frame still missing packets when a newer frame starts is
dropped and counted, because a frame with holes would make false detections.
"""

import socket
import struct
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import numpy.typing as npt

from upchirp.config import ChirpConfig
from upchirp.frame import Frame

MAGIC = b"UPC0"
VERSION = 0
STAGES = ("raw", "range")
FORMAT_INT16_IQ = 0
# magic, version, stage, sample format, n_rx, frame counter, chirp index, rx index,
# reserved, n_chirps, n_samples, first sample in this packet, samples in this packet,
# FPGA clock (ns)
HEADER = struct.Struct("<4sBBBBIHBBHHHHQ")
assert HEADER.size == 32
SAMPLE_BYTES = 4  # int16 I + int16 Q
FULL_SCALE = 32768.0
# 1472 bytes is the largest UDP payload that fits a standard 1500-byte Ethernet frame
MAX_SAMPLES_PER_PACKET = (1472 - HEADER.size) // SAMPLE_BYTES  # 360


@dataclass(frozen=True)
class Packet:
    stage: str
    n_rx: int
    frame_counter: int
    chirp: int
    rx: int
    n_chirps: int
    n_samples: int
    offset: int
    samples: npt.NDArray[np.complex64]
    fpga_time_ns: int


def decode_packet(buf: bytes) -> Packet:
    if len(buf) < HEADER.size:
        raise ValueError("packet shorter than its header")
    (magic, version, stage, fmt, n_rx, counter, chirp, rx, _, n_chirps, n_samples,
     offset, count, fpga_ns) = HEADER.unpack_from(buf)
    if magic != MAGIC:
        raise ValueError("not an Upchirp FPGA packet")
    if version != VERSION or fmt != FORMAT_INT16_IQ or stage >= len(STAGES):
        raise ValueError(f"unsupported packet: version {version}, format {fmt}, stage {stage}")
    if len(buf) != HEADER.size + count * SAMPLE_BYTES:
        raise ValueError(f"packet has {len(buf)} bytes, header says {count} samples")
    if rx >= n_rx or chirp >= n_chirps or offset + count > n_samples:
        raise ValueError("packet indexes outside the frame")
    iq = np.frombuffer(buf, dtype="<i2", offset=HEADER.size).astype(np.float32) / FULL_SCALE
    samples = (iq[0::2] + 1j * iq[1::2]).astype(np.complex64)
    return Packet(STAGES[stage], n_rx, counter, chirp, rx, n_chirps, n_samples, offset,
                  samples, fpga_ns)


def encode_packets(cube: npt.NDArray[np.complexfloating[Any, Any]], frame_counter: int,
                   fpga_time_ns: int = 0, stage: str = "raw",
                   max_samples: int = MAX_SAMPLES_PER_PACKET) -> list[bytes]:
    """What the FPGA would send for one frame. Used by the fake FPGA and the tests;
    the real encoder is Abdullah's RTL. Samples are clipped to the int16 range."""
    n_rx, n_chirps, n_samples = cube.shape
    iq = np.empty((*cube.shape, 2), dtype=np.float64)
    iq[..., 0], iq[..., 1] = cube.real, cube.imag
    q = np.clip(np.round(iq * FULL_SCALE), -32768, 32767).astype("<i2")
    out = []
    for rx in range(n_rx):
        for chirp in range(n_chirps):
            for offset in range(0, n_samples, max_samples):
                part = q[rx, chirp, offset:offset + max_samples]
                header = HEADER.pack(MAGIC, VERSION, STAGES.index(stage), FORMAT_INT16_IQ,
                                     n_rx, frame_counter & 0xFFFFFFFF, chirp, rx, 0,
                                     n_chirps, n_samples, offset, len(part), fpga_time_ns)
                out.append(header + part.tobytes())
    return out


@dataclass
class _Partial:
    first: Packet
    received_ns: int
    cube: npt.NDArray[np.complex64]
    filled: int = 0


@dataclass
class Reassembler:
    """Turns packets into Frames. Keeps at most a few frames open at once."""

    session_id: str
    chirp: ChirpConfig
    max_open: int = 2
    frames_out: int = 0
    frames_dropped: int = 0
    bad_packets: int = 0
    _open: dict[int, _Partial] = field(default_factory=dict)
    _seen: set[tuple[int, int, int, int]] = field(default_factory=set)

    def feed(self, buf: bytes, received_ns: int | None = None) -> Frame | None:
        try:
            p = decode_packet(buf)
        except ValueError:
            self.bad_packets += 1
            return None
        if (p.n_chirps, p.n_samples) != (self.chirp.n_chirps, self.chirp.n_samples):
            self.bad_packets += 1  # the FPGA runs a different chirp config than we expect
            return None
        key = (p.frame_counter, p.rx, p.chirp, p.offset)
        if key in self._seen:
            return None  # a duplicate
        partial = self._open.get(p.frame_counter)
        if partial is None:
            if self._open and p.frame_counter < min(self._open):
                self.bad_packets += 1  # a late packet for a frame already given up
                return None
            partial = _Partial(p, received_ns or time.time_ns(),
                               np.zeros((p.n_rx, p.n_chirps, p.n_samples), np.complex64))
            self._open[p.frame_counter] = partial
            while len(self._open) > self.max_open:
                self._drop(min(self._open))
        self._seen.add(key)
        partial.cube[p.rx, p.chirp, p.offset:p.offset + len(p.samples)] = p.samples
        partial.filled += len(p.samples)
        if partial.filled < partial.cube.size:
            return None
        # every older frame still open is missing packets that are not coming
        for counter in [c for c in self._open if c < p.frame_counter]:
            self._drop(counter)
        del self._open[p.frame_counter]
        self._forget(p.frame_counter)
        frame = Frame.from_cube(
            partial.cube, source="fpga", session_id=self.session_id,
            frame_index=self.frames_out, timestamp_ns=partial.received_ns,
            chirp_config_id=self.chirp.id, stage=partial.first.stage,
            meta={"fpga_frame_counter": p.frame_counter,
                  "fpga_time_ns": partial.first.fpga_time_ns})
        self.frames_out += 1
        return frame

    def _drop(self, counter: int) -> None:
        del self._open[counter]
        self._forget(counter)
        self.frames_dropped += 1

    def _forget(self, counter: int) -> None:
        self._seen = {k for k in self._seen if k[0] != counter}


class FpgaSource:
    """Listens for FPGA packets on a UDP port and yields Frames."""

    def __init__(self, session_id: str, chirp: ChirpConfig | None = None,
                 host: str = "0.0.0.0", port: int = 4991,
                 idle_timeout_s: float | None = None) -> None:
        self.chirp = chirp or ChirpConfig()
        self.reassembler = Reassembler(session_id, self.chirp)
        self.host, self.port = host, port
        self.idle_timeout_s = idle_timeout_s

    def frames(self) -> Iterator[Frame]:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8 * 1024 * 1024)
            sock.bind((self.host, self.port))
            sock.settimeout(self.idle_timeout_s)
            while True:
                try:
                    buf = sock.recv(2048)
                except TimeoutError:
                    return  # the FPGA went quiet
                frame = self.reassembler.feed(buf)
                if frame is not None:
                    yield frame


def send_frames(frames: Iterator[Frame], host: str = "127.0.0.1", port: int = 4991,
                realtime: bool = True, frame_period_s: float = 0.1,
                headroom: float = 0.5) -> int:
    """A fake FPGA: sends frames as FPGA packets. For testing without hardware.
    Simulated samples are not in ADC units, so they are scaled once, from the first
    frame, to `headroom` of the int16 full scale (like a real ADC with a gain set)."""
    sent = 0
    gain: float | None = None
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        start = time.monotonic()
        for i, frame in enumerate(frames):
            cube = frame.cube()
            if gain is None:
                peak = float(max(np.abs(cube.real).max(), np.abs(cube.imag).max()))
                gain = headroom / peak if peak > 0 else 1.0
            for packet in encode_packets(cube * gain, i, fpga_time_ns=frame.timestamp_ns,
                                         stage=frame.stage):
                sock.sendto(packet, (host, port))
            sent += 1
            if realtime:
                time.sleep(max(0.0, start + (i + 1) * frame_period_s - time.monotonic()))
    return sent
