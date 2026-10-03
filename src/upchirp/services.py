"""The three stream services. Each runs as its own process on the edge box.

    source     any FrameSource -> topic "frames"
    processor  "frames" -> pipeline -> "detections", "tracks", "rdmaps"
    writer     "detections", "tracks" -> PostgreSQL

The processor never knows which source produced a frame (decision 0003). A new
run starts whenever the session changes or frame numbers go backwards (a replay
loop), so track ids never collide.
"""

import base64
import json
import time
import uuid
from collections.abc import Iterable
from typing import Any

import numpy as np
import numpy.typing as npt

from upchirp import metrics, store, stream, telemetry
from upchirp.config import ArrayConfig, ChirpConfig
from upchirp.frame import Frame, from_wire, to_wire
from upchirp.pipeline import Pipeline

CHIRP_CONFIGS = {c.id: c for c in (ChirpConfig(),)}


def chirp_config_for(frame: Frame) -> ChirpConfig:
    """Known configs by id; coffee-can configs are rebuilt from their id."""
    if frame.chirp_config_id in CHIRP_CONFIGS:
        return CHIRP_CONFIGS[frame.chirp_config_id]
    if frame.chirp_config_id.startswith("coffee-can-"):
        from upchirp.sources.soundcard import CoffeeCanConfig

        _, _, mhz, khz = frame.chirp_config_id.split("-")
        cfg = CoffeeCanConfig(bandwidth_hz=float(mhz.removesuffix("mhz")) * 1e6,
                              chirps_per_frame=frame.n_chirps)
        return cfg.chirp_config(float(khz.removesuffix("k")) * 1e3)
    raise ValueError(f"unknown chirp config '{frame.chirp_config_id}'")
RDMAP_DYNAMIC_RANGE_DB = 60.0


def run_source(frames: Iterable[Frame], label: str = "source") -> int:
    """Publish frames to the 'frames' topic. Returns how many were sent."""
    tracer = telemetry.setup(label)
    prod = stream.producer()
    count = 0
    for frame in frames:
        with tracer.start_as_current_span("publish_frame") as span:
            span.set_attribute("frame_index", frame.frame_index)
            prod.produce(stream.topic(stream.FRAMES), to_wire(frame), key=frame.session_id.encode())
            prod.poll(0)
            count += 1
            metrics.FRAMES_PUBLISHED.inc()
    prod.flush(30)
    return count


def rdmap_message(power: npt.NDArray[Any], chirp: ChirpConfig) -> dict[str, Any]:
    """An 8-bit image of the range-Doppler map: 0 at the median noise, 255 at +60 dB."""
    db = 10 * np.log10(power + 1e-30)
    img = np.clip((db - np.median(db)) * (255 / RDMAP_DYNAMIC_RANGE_DB), 0, 255).astype(np.uint8)
    return {
        "shape": list(img.shape),  # [doppler, range]
        "range_bin_m": chirp.range_bin_m,
        "velocity_bin_mps": chirp.velocity_bin_mps,
        "dynamic_range_db": RDMAP_DYNAMIC_RANGE_DB,
        "data": base64.b64encode(img.tobytes()).decode(),
    }


class Processor:
    def __init__(self) -> None:
        self.tracer = telemetry.setup("processor")
        self.prod = stream.producer()
        self.pipeline: Pipeline | None = None
        self.run_id = ""
        self.session_id = ""
        self.last_index = -1

    def _start_run(self, frame: Frame) -> None:
        chirp = chirp_config_for(frame)
        self.pipeline = Pipeline(chirp, ArrayConfig(n_rx=frame.n_rx))
        self.session_id = frame.session_id
        self.run_id = f"{frame.session_id}#{uuid.uuid4().hex[:8]}"

    def handle(self, frame: Frame) -> None:
        if (self.pipeline is None or frame.session_id != self.session_id
                or frame.frame_index <= self.last_index):
            self._start_run(frame)
        self.last_index = frame.frame_index
        assert self.pipeline is not None
        with (self.tracer.start_as_current_span("process_frame") as span,
              metrics.FRAME_SECONDS.time()):
            span.set_attribute("run_id", self.run_id)
            span.set_attribute("frame_index", frame.frame_index)
            result = self.pipeline.process(frame)
            span.set_attribute("detections", len(result.detections))
        metrics.FRAMES_PROCESSED.inc()
        metrics.DETECTIONS.inc(len(result.detections))
        metrics.CONFIRMED_TRACKS.set(sum(t.confirmed for t in result.tracks))
        head = {"run_id": self.run_id, "session_id": frame.session_id, "source": frame.source,
                "frame_index": frame.frame_index, "timestamp_ns": frame.timestamp_ns}
        key = self.run_id.encode()
        self.prod.produce(stream.topic(stream.DETECTIONS), key=key, value=stream.encode(
            {**head, "detections": stream.rows(result.detections)}))
        self.prod.produce(stream.topic(stream.TRACKS), key=key, value=stream.encode(
            {**head, "tracks": stream.rows(result.tracks)}))
        power = self.pipeline.detector.last_power
        if power is not None:
            self.prod.produce(stream.topic(stream.RDMAPS), key=key, value=stream.encode(
                {**head, **rdmap_message(power, self.pipeline.chirp)}))
        self.prod.poll(0)


def run_processor(from_start: bool = False, max_idle_s: float | None = None) -> None:
    metrics.serve_from_env()
    stream.ensure_topics()
    proc = Processor()
    cons = stream.consumer("upchirp-processor", [stream.FRAMES], from_start)
    idle_since = time.monotonic()
    try:
        for item in stream.messages(cons):
            if item is None:
                proc.prod.flush(5)
                if max_idle_s is not None and time.monotonic() - idle_since > max_idle_s:
                    return
                continue
            idle_since = time.monotonic()
            proc.handle(from_wire(item[1]))
    finally:
        proc.prod.flush(10)
        cons.close()


def run_writer(from_start: bool = False, max_idle_s: float | None = None) -> None:
    """Write detections and confirmed tracks to Postgres in small batches."""
    tracer = telemetry.setup("writer")
    metrics.serve_from_env()
    stream.ensure_topics()
    conn = store.connect_waiting()
    store.init_schema(conn)
    cons = stream.consumer("upchirp-writer", [stream.DETECTIONS, stream.TRACKS], from_start)
    pending: list[tuple[str, dict[str, Any]]] = []
    idle_since = time.monotonic()

    def flush() -> None:
        if not pending:
            return
        with tracer.start_as_current_span("write_batch") as span:
            span.set_attribute("messages", len(pending))
            with conn.transaction():
                for topic, msg in pending:
                    if topic == stream.DETECTIONS:
                        store.insert_detections(conn, msg["run_id"], msg["detections"])
                        metrics.ROWS_WRITTEN.labels("detections").inc(len(msg["detections"]))
                    else:
                        store.upsert_run(conn, msg["run_id"], msg["session_id"], msg["source"],
                                         msg["timestamp_ns"], frames=1)
                        confirmed = [t for t in msg["tracks"] if t["confirmed"]]
                        store.insert_tracks(conn, msg["run_id"], confirmed)
                        metrics.ROWS_WRITTEN.labels("tracks").inc(len(confirmed))
        pending.clear()

    try:
        for item in stream.messages(cons):
            if item is None:
                flush()
                if max_idle_s is not None and time.monotonic() - idle_since > max_idle_s:
                    return
                continue
            idle_since = time.monotonic()
            pending.append((item[0], json.loads(item[1])))
            if len(pending) >= 50:
                flush()
    finally:
        flush()
        cons.close()
        conn.close()
