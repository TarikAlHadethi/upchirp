"""Prometheus metrics for system health (step 7). Grafana reads these; radar data stays in Postgres.

Stream services serve /metrics on UPCHIRP_METRICS_PORT when it is set; the API
serves /metrics on its own port.
"""

import os

from prometheus_client import Counter, Gauge, Histogram, start_http_server

FRAMES_PUBLISHED = Counter("upchirp_frames_published_total", "Frames sent to the stream")
FRAMES_PROCESSED = Counter("upchirp_frames_processed_total", "Frames run through the pipeline")
FRAME_SECONDS = Histogram("upchirp_frame_processing_seconds", "Pipeline time per frame",
                          buckets=(0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0))
DETECTIONS = Counter("upchirp_detections_total", "Detections produced")
CONFIRMED_TRACKS = Gauge("upchirp_confirmed_tracks", "Confirmed tracks in the newest frame")
ROWS_WRITTEN = Counter("upchirp_rows_written_total", "Rows written to Postgres", ["table"])
QUESTIONS = Counter("upchirp_agent_questions_total", "Questions to the agent", ["outcome"])
ANSWER_SECONDS = Histogram("upchirp_agent_answer_seconds", "Time to answer a question",
                           buckets=(1, 2, 5, 10, 20, 30, 60, 120))
BAD_MESSAGES = Counter("upchirp_bad_messages_total", "Stream messages skipped as unreadable",
                       ["service"])
LIVE_CLIENTS = Gauge("upchirp_live_clients", "Browsers on the live view")


def serve_from_env() -> None:
    port = os.environ.get("UPCHIRP_METRICS_PORT")
    if port:
        start_http_server(int(port))
