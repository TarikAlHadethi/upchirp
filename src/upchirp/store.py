"""PostgreSQL + TimescaleDB + pgvector: one database for detections, tracks, audit and RAG.

A run is one pass of the pipeline over a session (a replay looped three times
is three runs of the same session). Track ids are only unique within a run.
"""

import json
import os
import time
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row

from upchirp.dsp.tracker import TrackState

SCHEMA = """
CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS runs (
    run_id      text PRIMARY KEY,
    session_id  text NOT NULL,
    source      text NOT NULL,
    first_ts    timestamptz NOT NULL,
    last_ts     timestamptz NOT NULL,
    frames      integer NOT NULL DEFAULT 0
);
-- when the run was last written. "latest" means this, not the recording's own clock,
-- because a replay of an old recording is still the newest thing happening.
ALTER TABLE runs ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now();

CREATE TABLE IF NOT EXISTS detections (
    ts                  timestamptz NOT NULL,
    run_id              text NOT NULL,
    frame_index         integer NOT NULL,
    range_m             real,
    radial_velocity_mps real,
    azimuth_deg         real,
    snr_db              real
);
SELECT create_hypertable('detections', 'ts', if_not_exists => true);
CREATE INDEX IF NOT EXISTS detections_run ON detections (run_id, ts);

CREATE TABLE IF NOT EXISTS tracks (
    ts                  timestamptz NOT NULL,
    run_id              text NOT NULL,
    frame_index         integer NOT NULL,
    track_id            integer NOT NULL,
    confirmed           boolean NOT NULL,
    x_m real, y_m real, vx_mps real, vy_mps real,
    range_m real, azimuth_deg real, radial_velocity_mps real, speed_mps real,
    hits integer, misses integer,
    label               text,
    rcs_dbsm            real
);
SELECT create_hypertable('tracks', 'ts', if_not_exists => true);
CREATE INDEX IF NOT EXISTS tracks_run ON tracks (run_id, ts);

CREATE TABLE IF NOT EXISTS audit (
    ts      timestamptz NOT NULL DEFAULT now(),
    actor   text NOT NULL,
    event   jsonb NOT NULL
);

CREATE TABLE IF NOT EXISTS doc_chunks (
    id          serial PRIMARY KEY,
    doc         text NOT NULL,
    chunk       text NOT NULL,
    embedding   vector(768) NOT NULL
);
"""

TRACK_COLUMNS = (
    "frame_index", "track_id", "confirmed", "x_m", "y_m", "vx_mps", "vy_mps", "range_m",
    "azimuth_deg", "radial_velocity_mps", "speed_mps", "hits", "misses", "label", "rcs_dbsm",
)


def database_url() -> str | None:
    return os.environ.get("UPCHIRP_DATABASE_URL")


def connect() -> psycopg.Connection[dict[str, Any]]:
    url = database_url()
    if not url:
        raise RuntimeError("UPCHIRP_DATABASE_URL is not set")
    return connect_to(url)


def connect_to(url: str) -> psycopg.Connection[dict[str, Any]]:
    return psycopg.connect(url, row_factory=dict_row, autocommit=True, connect_timeout=10)


def connect_waiting(timeout_s: float = 120) -> psycopg.Connection[dict[str, Any]]:
    """Connect, retrying while the database starts (services can start before it)."""
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            return connect()
        except psycopg.OperationalError:
            if time.monotonic() > deadline:
                raise
            time.sleep(3)


def init_schema(conn: psycopg.Connection[Any]) -> None:
    conn.execute(SCHEMA)
    # A box that runs for weeks (the public demo) keeps only recent detections and tracks,
    # so the database cannot fill the disk. Unset keeps everything (the edge box).
    days = os.environ.get("UPCHIRP_DB_RETENTION_DAYS")
    if days:
        for table in ("detections", "tracks"):
            conn.execute(
                f"SELECT add_retention_policy('{table}', INTERVAL '{int(days)} days', "
                "if_not_exists => true)")


def ts(ns: int) -> datetime:
    return datetime.fromtimestamp(ns / 1e9, UTC)


def upsert_run(conn: psycopg.Connection[Any], run_id: str, session_id: str, source: str,
               timestamp_ns: int, frames: int) -> None:
    conn.execute(
        """INSERT INTO runs (run_id, session_id, source, first_ts, last_ts, frames)
           VALUES (%s, %s, %s, %s, %s, %s)
           ON CONFLICT (run_id) DO UPDATE
           SET last_ts = GREATEST(runs.last_ts, EXCLUDED.last_ts),
               frames = runs.frames + EXCLUDED.frames,
               updated_at = now()""",
        (run_id, session_id, source, ts(timestamp_ns), ts(timestamp_ns), frames),
    )


def insert_detections(conn: psycopg.Connection[Any], run_id: str,
                      rows: Iterable[dict[str, Any]]) -> None:
    with conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO detections (ts, run_id, frame_index, range_m, radial_velocity_mps,
               azimuth_deg, snr_db) VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            [(ts(r["timestamp_ns"]), run_id, r["frame_index"], r["range_m"],
              r["radial_velocity_mps"], r["azimuth_deg"], r["snr_db"]) for r in rows],
        )


def insert_tracks(conn: psycopg.Connection[Any], run_id: str,
                  rows: Iterable[dict[str, Any]]) -> None:
    cols = ", ".join(TRACK_COLUMNS)
    marks = ", ".join(["%s"] * (len(TRACK_COLUMNS) + 2))
    with conn.cursor() as cur:
        cur.executemany(
            f"INSERT INTO tracks (ts, run_id, {cols}) VALUES ({marks})",
            [(ts(r["timestamp_ns"]), run_id, *(r[c] for c in TRACK_COLUMNS)) for r in rows],
        )


def insert_audit(conn: psycopg.Connection[Any], event: dict[str, Any]) -> None:
    actor = str(event.get("actor", "unknown"))
    conn.execute("INSERT INTO audit (actor, event) VALUES (%s, %s)",
                 (actor, json.dumps(event, default=str)))


def list_runs(conn: psycopg.Connection[dict[str, Any]]) -> list[dict[str, Any]]:
    return conn.execute(
        "SELECT run_id, session_id, source, first_ts, last_ts, frames FROM runs "
        "ORDER BY updated_at DESC, run_id DESC"
    ).fetchall()


def resolve_run(conn: psycopg.Connection[dict[str, Any]], session: str) -> dict[str, Any]:
    """'latest' is the run written most recently; otherwise a run id, or the most recently
    written run of a session id."""
    if session == "latest":
        row = conn.execute("SELECT * FROM runs ORDER BY updated_at DESC LIMIT 1").fetchone()
    else:
        row = conn.execute(
            "SELECT * FROM runs WHERE run_id = %s OR session_id = %s "
            "ORDER BY updated_at DESC LIMIT 1", (session, session)).fetchone()
    if row is None:
        raise FileNotFoundError(f"no run found for '{session}'")
    return row


def load_track_states(conn: psycopg.Connection[dict[str, Any]], run_id: str
                      ) -> list[TrackState]:
    rows = conn.execute(
        f"SELECT ts, run_id, {', '.join(TRACK_COLUMNS)} FROM tracks "
        "WHERE run_id = %s AND confirmed ORDER BY ts, track_id", (run_id,)).fetchall()
    out = []
    for r in rows:
        ts_ns = int(r.pop("ts").timestamp() * 1e9)
        run = r.pop("run_id")
        r = {k: (float("nan") if v is None and k == "rcs_dbsm" else v) for k, v in r.items()}
        out.append(TrackState(session_id=run, timestamp_ns=ts_ns, **r))
    return out
