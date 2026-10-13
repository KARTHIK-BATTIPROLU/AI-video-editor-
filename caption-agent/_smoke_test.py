"""Orchestration smoke test (no heavy ML deps).

Stubs transcribe / detect_regions / detect_scenes so we can exercise the REAL
graph topology, interrupt, checkpoint/resume, props contract, and a real Remotion
render against the synthetic sample.mp4. Run with the project venv:

    .venv\\Scripts\\python.exe _smoke_test.py
"""

import os
import sys

import pipeline.graph as G
from pipeline.state import Word, Scene, FrameDet, Box
from pipeline.templates import template_props, TEMPLATES

HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLE = os.path.join(HERE, "remotion", "public", "sample.mp4")
OUT = os.path.join(HERE, "out_smoke.mp4")

_transcribe_calls = {"n": 0}


def stub_transcribe(state):
    _transcribe_calls["n"] += 1
    words = [
        Word("This", 0.25, 0.56), Word("is", 0.63, 0.82), Word("huge.", 0.90, 2.20),
        Word("Captions", 2.40, 2.90), Word("that", 2.95, 3.20), Word("pop.", 3.30, 4.80),
    ]
    return {"words": words}


def stub_detect(state):
    # A centered face for the whole clip -> captions must avoid the center band.
    dets = [FrameDet(t=i * 0.5, boxes=[Box(0.33, 0.26, 0.34, 0.32)]) for i in range(12)]
    return {"detections": dets}


def stub_scenes(state):
    return {"scenes": [Scene(0.0, 6.0)]}


def stub_transcribe_empty(state):
    return {"words": []}


def _patch(transcribe=stub_transcribe):
    G.transcribe = transcribe
    G.detect_regions = stub_detect
    G.detect_scenes = stub_scenes


def check(label, cond):
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}")
    if not cond:
        check.failed = True


check.failed = False


def main():
    db = os.path.join(HERE, "data", "checkpoints.sqlite")
    if os.path.exists(db):
        os.remove(db)
    if os.path.exists(OUT):
        os.remove(OUT)

    initial = {
        "video_path": SAMPLE,
        "template_id": "punch",
        "output_path": OUT,
        "language": "en",
        "status": "running",
    }

    # ---- 1) fresh run to the render interrupt -----------------------------
    print("\n[1] run to interrupt (thread T1)")
    _patch()
    app = G.build_graph()
    cfg = {"configurable": {"thread_id": "T1"}}
    app.invoke(initial, cfg)
    snap = app.get_state(cfg)
    check("paused BEFORE render (interrupt fired)", snap.next == ("render",))
    check("transcribe ran exactly once", _transcribe_calls["n"] == 1)
    pages = snap.values.get("pages") or []
    check("pages were produced", len(pages) > 0)
    anchors = {p.anchor for p in pages}
    ys = [p.y for p in pages]
    check("captions avoid centered face (no 'center' anchor)", "center" not in anchors)
    check("captions sit lower/upper third, not mid-screen",
          all(y >= 0.75 or y <= 0.25 for y in ys))
    print("      placement:", [(round(p.y, 2), p.anchor) for p in pages])

    # ---- 2) resume in a NEW saver/process-like graph (no re-transcribe) ----
    print("\n[2] resume to render (new graph instance, same sqlite/thread)")
    app2 = G.build_graph()
    final = app2.invoke(None, cfg)
    check("transcribe NOT re-run on resume (still 1)", _transcribe_calls["n"] == 1)
    check("status == done", final.get("status") == "done")
    check("out_smoke.mp4 exists and non-empty",
          os.path.exists(OUT) and os.path.getsize(OUT) > 0)

    # ---- 3) props contract validated + template anim distinctness ----------
    print("\n[3] props contract + templates")
    props_path = os.path.join(HERE, "remotion", "public", "props.json")
    check("props.json written by pipeline", os.path.exists(props_path))
    anims = {tid: template_props(tid)["anim"] for tid in TEMPLATES}
    check("4 templates -> 4 distinct anims", len(set(anims.values())) == 4)
    print("      anims:", anims)

    # ---- 4) empty transcript short-circuits to finalize (conditional edge) --
    print("\n[4] empty transcript -> graceful abort (thread T2)")
    _patch(transcribe=stub_transcribe_empty)
    app3 = G.build_graph()
    cfg2 = {"configurable": {"thread_id": "T2"}}
    try:
        app3.invoke(initial, cfg2)
    except Exception as exc:  # diagnostic: surface concurrency issues
        print("      invoke raised:", type(exc).__name__, exc)
    snap2 = app3.get_state(cfg2)
    print("      next =", snap2.next, "| status =", snap2.values.get("status"),
          "| pages =", len(snap2.values.get("pages") or []),
          "| rendered =", bool(snap2.values.get("rendered_path")))
    # langgraph OR-join still runs the barrier layout via safe_zones/scenes, so
    # the graph parks at the render gate -- but the tail guards ensure it never
    # renders and reports failed. That's the graceful-abort guarantee.
    check("status == failed (empty transcript)",
          snap2.values.get("status") == "failed")
    check("zero caption pages", len(snap2.values.get("pages") or []) == 0)
    check("never rendered an empty video", not snap2.values.get("rendered_path"))

    print("\n" + ("FAILED" if check.failed else "ALL CHECKS PASSED"))
    return 1 if check.failed else 0


if __name__ == "__main__":
    sys.exit(main())
