"""
OpenTelemetry distributed tracing setup.

Instruments:
- FastAPI (via opentelemetry-instrumentation-fastapi)
- LLM calls (manual spans)
- Agent execution (manual spans)

Configure via env vars:
  OTEL_EXPORTER_OTLP_ENDPOINT   (default: http://localhost:4318)
  OTEL_SERVICE_NAME             (default: agent-system)
  OTEL_ENABLED                  (default: false — set to "true" to enable)
"""
import logging
import os
from contextlib import contextmanager
from typing import Generator

logger = logging.getLogger(__name__)

_enabled = os.getenv("OTEL_ENABLED", "false").lower() == "true"
_tracer = None


def setup_tracing(app=None) -> None:
    """Initialize OpenTelemetry. Call once at startup."""
    global _tracer, _enabled

    if not _enabled:
        logger.debug("OpenTelemetry tracing disabled (set OTEL_ENABLED=true to enable)")
        return

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.resources import Resource

        resource = Resource.create({
            "service.name": os.getenv("OTEL_SERVICE_NAME", "agent-system"),
            "service.version": "2.0.0",
        })

        provider = TracerProvider(resource=resource)

        endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            exporter = OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces")
            provider.add_span_processor(BatchSpanProcessor(exporter))
            logger.info("OTLP tracing exporter configured → %s", endpoint)
        except Exception as exc:
            logger.warning("OTLP exporter unavailable (%s) — using console", exc)
            from opentelemetry.sdk.trace.export import ConsoleSpanExporter
            provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))

        trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer("agent-system")

        # Auto-instrument FastAPI if app is provided
        if app is not None:
            try:
                from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
                FastAPIInstrumentor.instrument_app(app)
                logger.info("FastAPI instrumented with OpenTelemetry")
            except Exception as exc:
                logger.warning("FastAPI instrumentation failed: %s", exc)

    except ImportError:
        logger.warning("opentelemetry packages not installed — tracing disabled")
        _enabled = False


@contextmanager
def span(name: str, attributes: dict | None = None) -> Generator:
    """Context manager that creates a tracing span if OTel is enabled."""
    if not _enabled or _tracer is None:
        yield _NoopSpan()
        return

    from opentelemetry import trace as _trace
    with _tracer.start_as_current_span(name) as s:
        if attributes:
            for k, v in attributes.items():
                s.set_attribute(k, str(v))
        yield s


def record_llm_call(model: str, input_tokens: int, output_tokens: int,
                     cost_usd: float, duration_ms: float) -> None:
    """Record LLM call metrics as span attributes."""
    if not _enabled or _tracer is None:
        return
    with span("llm.call", {
        "llm.model": model,
        "llm.input_tokens": input_tokens,
        "llm.output_tokens": output_tokens,
        "llm.cost_usd": cost_usd,
        "llm.duration_ms": duration_ms,
    }):
        pass


def record_agent_run(agent_name: str, session_id: str, iterations: int,
                      success: bool) -> None:
    """Record agent execution metrics."""
    if not _enabled or _tracer is None:
        return
    with span("agent.run", {
        "agent.name": agent_name,
        "agent.session_id": session_id,
        "agent.iterations": iterations,
        "agent.success": success,
    }):
        pass


class _NoopSpan:
    """No-op span when tracing is disabled."""
    def set_attribute(self, key: str, value) -> None:
        pass
    def set_status(self, *args, **kwargs) -> None:
        pass
    def record_exception(self, exc) -> None:
        pass
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
