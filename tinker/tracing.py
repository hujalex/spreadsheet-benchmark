import atexit
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import phoenix as px
from phoenix.otel import register
from openinference.semconv.trace import OpenInferenceSpanKindValues, SpanAttributes
from opentelemetry import trace as _otel_trace


PHOENIX_PROJECT_NAME = os.getenv("PHOENIX_PROJECT_NAME", "spreadsheet-agent-benchmark-tinker")
PHOENIX_ENDPOINT = os.getenv("PHOENIX_COLLECTOR_ENDPOINT", "http://localhost:6006/v1/traces")
TRACES_DIR = Path(os.getenv("PHOENIX_TRACES_DIR", "traces"))


def _normalize_phoenix_endpoint(endpoint: str) -> str:
    endpoint = endpoint.rstrip("/")
    if endpoint.endswith("/v1/traces"):
        return endpoint
    return f"{endpoint}/v1/traces"


def _phoenix_base_url(endpoint: str) -> str:
    endpoint = endpoint.rstrip("/")
    if endpoint.endswith("/v1/traces"):
        endpoint = endpoint[: -len("/v1/traces")]
    return endpoint


def save_traces_to_disk(out_dir: Path | str | None = None, project_name: str | None = None) -> Path | None:
    """Flush pending spans and persist all spans for the project to disk as parquet."""
    out_dir = Path(out_dir) if out_dir is not None else TRACES_DIR
    project_name = project_name or PHOENIX_PROJECT_NAME
    base_url = _phoenix_base_url(PHOENIX_ENDPOINT)
    try:
        provider = _otel_trace.get_tracer_provider()
        if hasattr(provider, "force_flush"):
            provider.force_flush()
    except Exception as e:
        print(f"[traces] tracer flush failed: {e}")
    try:
        from phoenix.client import Client
        client = Client(
            base_url=base_url,
            api_key=os.getenv("PHOENIX_API_KEY") or os.getenv("ARIZE_PHOENIX_API_KEY"),
        )
        df = client.spans.get_spans_dataframe(project_name=project_name, limit=1_000_000, timeout=30)
    except Exception as e:
        print(f"[traces] failed to fetch spans from Phoenix: {e}")
        return None
    if df is None or len(df) == 0:
        print("[traces] no spans returned from Phoenix; nothing to save")
        return None
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = out_dir / f"{project_name}-{ts}.parquet"
    try:
        df.to_parquet(path)
    except Exception as e:
        path = path.with_suffix(".jsonl")
        df.to_json(path, orient="records", lines=True, date_format="iso")
        print(f"[traces] parquet failed ({e}); wrote JSONL instead")
    print(f"[traces] saved {len(df)} spans to {path}")
    return path


def _register_export_atexit(out_dir: Path | str | None = None, project_name: str | None = None) -> None:
    atexit.register(save_traces_to_disk, out_dir, project_name)


def setup_phoenix_tracing():
    endpoint = _normalize_phoenix_endpoint(PHOENIX_ENDPOINT)
    session = None
    launch_requested = os.getenv("PHOENIX_LAUNCH_APP", "1") != "0"
    local_endpoint = "localhost" in endpoint or "127.0.0.1" in endpoint
    if launch_requested and local_endpoint:
        session = px.launch_app()
        print(f"Phoenix UI: {session.url}")

    register(
        project_name=PHOENIX_PROJECT_NAME,
        endpoint=endpoint,
        protocol="http/protobuf",
        auto_instrument=False,
        batch=True,
        api_key=os.getenv("PHOENIX_API_KEY") or os.getenv("ARIZE_PHOENIX_API_KEY"),
    )
    print(f"Phoenix tracing: project={PHOENIX_PROJECT_NAME}, endpoint={endpoint}")
    _register_export_atexit()
    print(f"Phoenix traces will be persisted to {TRACES_DIR.resolve()} on exit")
    return session


def set_span_kind(span, kind: OpenInferenceSpanKindValues) -> None:
    span.set_attribute(SpanAttributes.OPENINFERENCE_SPAN_KIND, kind.value)


@contextmanager
def span(tracer, name: str, kind: OpenInferenceSpanKindValues, **attrs):
    with tracer.start_as_current_span(name) as s:
        set_span_kind(s, kind)
        for k, v in attrs.items():
            s.set_attribute(k, v)
        yield s
