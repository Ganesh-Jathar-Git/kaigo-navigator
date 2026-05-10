"""
Langfuse observability wrapper.
Every agent node is traced — inputs, outputs, model, cost, confidence.
Compatible with Langfuse v3+.
"""

import functools
import time
from typing import Any, Callable, Optional
from config.settings import get_settings

settings = get_settings()

try:
    from langfuse import Langfuse

    _client = Langfuse(
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key,
        host=settings.langfuse_host,
    )
    LANGFUSE_ENABLED = bool(settings.langfuse_public_key)
except Exception:
    _client = None
    LANGFUSE_ENABLED = False


def get_client():
    return _client


def start_trace(name: str, metadata: Optional[dict] = None):
    """Start a top-level Langfuse trace for a care request (v3 compatible)."""
    if not LANGFUSE_ENABLED or _client is None:
        return None
    try:
        span = _client.start_span(name=name, metadata=metadata or {})
        return span
    except Exception:
        return None


def trace_agent_step(
    trace,
    step_name: str,
    input_data: Any,
    output_data: Any,
    model: Optional[str] = None,
    metadata: Optional[dict] = None,
    confidence: Optional[float] = None,
):
    """Record a single agent step as a child span under the root trace."""
    if not LANGFUSE_ENABLED or trace is None:
        return

    meta = metadata or {}
    if confidence is not None:
        meta["confidence_score"] = confidence
    if model:
        meta["model"] = model

    try:
        child = trace.start_span(
            name=step_name,
            input={"data": str(input_data)[:2000]},
            output={"data": str(output_data)[:2000]},
            metadata=meta,
        )
        child.end()
    except Exception:
        pass


def observe_node(step_name: str):
    """
    Decorator for LangGraph nodes.
    Wraps the node function with Langfuse tracing.

    Usage:
        @observe_node("service_discovery")
        def discovery_node(state: CareState) -> CareState:
            ...
    """
    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(state: dict, *args, **kwargs) -> dict:
            start = time.perf_counter()
            trace = state.get("_trace")

            try:
                result = fn(state, *args, **kwargs)
                elapsed = time.perf_counter() - start

                if LANGFUSE_ENABLED and trace:
                    try:
                        child = trace.start_span(
                            name=step_name,
                            input={"state_keys": list(state.keys())},
                            output={"state_keys": list(result.keys()) if result else []},
                            metadata={"elapsed_ms": round(elapsed * 1000, 2)},
                        )
                        child.end()
                    except Exception:
                        pass
                return result

            except Exception as e:
                if LANGFUSE_ENABLED and trace:
                    try:
                        child = trace.start_span(
                            name=step_name,
                            input={"state_keys": list(state.keys())},
                            output={"error": str(e)},
                            level="ERROR",
                        )
                        child.end()
                    except Exception:
                        pass
                raise

        return wrapper
    return decorator
