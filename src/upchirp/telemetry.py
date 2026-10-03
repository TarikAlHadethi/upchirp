"""OpenTelemetry tracing for system health (not radar data).

Spans export over OTLP when OTEL_EXPORTER_OTLP_ENDPOINT is set (step 7 adds the
collector, Prometheus and Grafana); otherwise they are created but not exported.
UPCHIRP_TRACE_CONSOLE=1 prints them, for debugging.
"""

import os
import threading

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

_configured = False
_lock = threading.Lock()


def setup(service: str) -> trace.Tracer:
    """Install the tracer provider once per process (thread-safe) and return a tracer."""
    global _configured
    with _lock:
        if not _configured:
            _install(service)
            _configured = True
    return trace.get_tracer(f"upchirp.{service}")


def _install(service: str) -> None:
    provider = TracerProvider(resource=Resource.create({"service.name": f"upchirp-{service}"}))
    if os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    if os.environ.get("UPCHIRP_TRACE_CONSOLE") == "1":
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(provider)
