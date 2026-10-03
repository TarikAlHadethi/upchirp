"""Redpanda topics and the thin Kafka helpers around them (decision 0001).

Topics:
    frames      Frame messages from any source (binary, see frame.to_wire)
    detections  one JSON message per frame: {run_id, session_id, frame_index, detections: [...]}
    tracks      one JSON message per frame: {run_id, ..., tracks: [...]}
    rdmaps      one JSON message per frame: a small 8-bit range-Doppler image for the live view

UPCHIRP_TOPIC_PREFIX keeps environments apart on one broker (tests, the public
demo); it prefixes every topic and consumer group.
"""

import json
import math
import os
import time
from collections.abc import Iterator
from dataclasses import asdict
from typing import Any

from confluent_kafka import Consumer, KafkaError, KafkaException, Producer

FRAMES = "frames"
DETECTIONS = "detections"
TRACKS = "tracks"
RDMAPS = "rdmaps"
ALL_TOPICS = (FRAMES, DETECTIONS, TRACKS, RDMAPS)


def prefix() -> str:
    return os.environ.get("UPCHIRP_TOPIC_PREFIX", "")


def topic(name: str) -> str:
    return prefix() + name


def base_topic(full: str) -> str:
    """The topic name without the environment prefix."""
    return full.removeprefix(prefix())


def bootstrap() -> str:
    return os.environ.get("UPCHIRP_KAFKA", "127.0.0.1:19092")


def producer() -> Producer:
    return Producer({
        "bootstrap.servers": bootstrap(),
        "linger.ms": 5,
        "message.max.bytes": 4_000_000,
        "compression.type": "lz4",
    })


def consumer(group: str, topics: list[str], from_start: bool = False) -> Consumer:
    c = Consumer({
        "bootstrap.servers": bootstrap(),
        "group.id": prefix() + group,
        "auto.offset.reset": "earliest" if from_start else "latest",
        "enable.auto.commit": True,
        "fetch.max.bytes": 50_000_000,
    })
    c.subscribe([topic(t) for t in topics])
    return c


def messages(c: Consumer, timeout_s: float = 0.5) -> Iterator[tuple[str, bytes] | None]:
    """Yield (topic, value) forever; None on each idle poll so callers can stop or flush."""
    while True:
        msg = c.poll(timeout_s)
        if msg is None:
            yield None
            continue
        err = msg.error()
        if err is not None:
            # a topic created a moment ago may not be visible yet: keep polling
            if err.code() in (KafkaError._PARTITION_EOF, KafkaError.UNKNOWN_TOPIC_OR_PART):
                yield None
                continue
            raise RuntimeError(err)
        yield base_topic(msg.topic() or ""), msg.value() or b""


def _clean(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    return value


def encode(payload: dict[str, Any]) -> bytes:
    return json.dumps(_clean(payload)).encode()


def rows(items: list[Any]) -> list[dict[str, Any]]:
    return [asdict(i) for i in items]


def ensure_topics(wait_s: float = 120) -> None:
    """Create the topics if they are missing (Redpanda auto-creates too, this sets sizes).

    Waits up to wait_s for the broker, which may start after the services do."""
    from confluent_kafka.admin import AdminClient, NewTopic  # type: ignore[attr-defined]

    admin = AdminClient({"bootstrap.servers": bootstrap()})
    deadline = time.monotonic() + wait_s
    while True:
        try:
            existing = set(admin.list_topics(timeout=10).topics)
            break
        except KafkaException:
            if time.monotonic() > deadline:
                raise
            time.sleep(3)
    new = [NewTopic(topic(t), num_partitions=1, replication_factor=1,
                    config={"max.message.bytes": "4000000", "retention.ms": str(6 * 3600_000)})
           for t in ALL_TOPICS if topic(t) not in existing]
    for future in admin.create_topics(new).values() if new else []:
        try:
            future.result()
        except KafkaException as e:  # another service created it first
            if e.args[0].code() != KafkaError.TOPIC_ALREADY_EXISTS:
                raise
