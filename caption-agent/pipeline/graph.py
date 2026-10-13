"""build_graph() — the FIXED DAG (MASTER_PROMPT §4).

Parallel section (transcribe / detect_regions+safe_zones / detect_scenes) fans in
at layout_captions. RetryPolicy handles transient failures; a conditional edge
after transcribe handles the logical dead-end of an empty transcript. SQLite
checkpointing + interrupt_before=["render"] give resumability and a human gate.
"""

import inspect
import sqlite3

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite import SqliteSaver

try:  # RetryPolicy moved across langgraph versions; import from wherever it lives.
    from langgraph.pregel import RetryPolicy
except ImportError:  # pragma: no cover
    from langgraph.types import RetryPolicy

from .state import CaptionState
from ._paths import DB_PATH
from .nodes import (
    probe_video,
    extract_audio,
    transcribe,
    detect_scenes,
    detect_regions,
    compute_safe_zones,
    layout_captions,
    write_remotion_props,
    render,
    finalize,
)

# add_node's retry kwarg was renamed `retry` -> `retry_policy` in langgraph 1.x.
_ADD_NODE_PARAMS = set(inspect.signature(StateGraph.add_node).parameters)
_RETRY_KW = "retry_policy" if "retry_policy" in _ADD_NODE_PARAMS else "retry"


def _retry(attempts: int) -> dict:
    return {_RETRY_KW: RetryPolicy(max_attempts=attempts)}


# `defer=True` turns a multi-predecessor node into a true BARRIER fan-in: it runs
# only once every other pending task is done. Without it, langgraph's OR-trigger
# semantics fire the node early (as soon as the first/shortest branch lands),
# which here made layout_captions run twice — once before transcribe finished.
_DEFER = {"defer": True} if "defer" in _ADD_NODE_PARAMS else {}


def route_after_transcribe(state: CaptionState) -> str:
    """Graceful abort: nothing to caption -> short-circuit to finalize."""
    if not state.get("words"):
        return "finalize"
    return "layout_captions"


def _build_builder() -> StateGraph:
    g = StateGraph(CaptionState)

    g.add_node("probe_video", probe_video)
    g.add_node("extract_audio", extract_audio)
    g.add_node("transcribe", transcribe, **_retry(3))
    g.add_node("detect_scenes", detect_scenes, **_retry(2))
    g.add_node("detect_regions", detect_regions, **_retry(2))
    g.add_node("compute_safe_zones", compute_safe_zones)
    g.add_node("layout_captions", layout_captions, **_DEFER)
    g.add_node("write_remotion_props", write_remotion_props)
    g.add_node("render", render, **_retry(2))
    g.add_node("finalize", finalize)

    g.add_edge(START, "probe_video")
    # fan-out
    g.add_edge("probe_video", "extract_audio")
    g.add_edge("probe_video", "detect_regions")
    g.add_edge("probe_video", "detect_scenes")
    # audio -> transcribe
    g.add_edge("extract_audio", "transcribe")
    # detections -> safe zones
    g.add_edge("detect_regions", "compute_safe_zones")
    # fan-in: layout waits for ALL three predecessors
    g.add_conditional_edges(
        "transcribe",
        route_after_transcribe,
        {"layout_captions": "layout_captions", "finalize": "finalize"},
    )
    g.add_edge("compute_safe_zones", "layout_captions")
    g.add_edge("detect_scenes", "layout_captions")
    # tail
    g.add_edge("layout_captions", "write_remotion_props")
    g.add_edge("write_remotion_props", "render")
    g.add_edge("render", "finalize")
    g.add_edge("finalize", END)

    return g


# Our state dataclasses, as (module, qualname) pairs the serializer allowlists.
_ALLOWED_TYPES = [
    ("pipeline.state", n)
    for n in ("Word", "Scene", "Box", "FrameDet", "SafeZone", "Page")
]


def _make_saver(conn) -> SqliteSaver:
    # Register our state dataclasses so the checkpoint serializer round-trips them
    # without the "unregistered type" warning (and future hard block). Guarded so
    # it still works on langgraph versions without `allowed_msgpack_modules`.
    try:
        from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
        serde = JsonPlusSerializer(allowed_msgpack_modules=_ALLOWED_TYPES)
        return SqliteSaver(conn, serde=serde)
    except Exception:  # pragma: no cover - older langgraph
        return SqliteSaver(conn)


def build_graph(db_path: str = str(DB_PATH)):
    """Compile the graph with a persistent SQLite checkpointer + render interrupt."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    # A long-lived connection (not the from_conn_string context manager) so the
    # saver outlives this call and persists every super-step to disk.
    conn = sqlite3.connect(db_path, check_same_thread=False)
    saver = _make_saver(conn)

    return _build_builder().compile(
        checkpointer=saver,
        interrupt_before=["render"],  # pause so a human can approve placement
    )
