# MASTER PROMPT — Reference-Style Auto-Caption Video Pipeline (LangGraph + Remotion)

> Paste this entire file into your coding agent (Claude Code / Cursor / etc.) at the root of an empty repo.
> Build it stage by stage in the order given. Do NOT skip the schemas or the graph topology — those are fixed decisions, not suggestions.

---

## 0. What you are building

A **stateful video-editing pipeline** that takes a raw talking-head video and burns in animated, word-synced captions that are *intelligently positioned to avoid faces*. The user picks one of four caption styles. The pipeline must be **resumable** — if a late stage fails, re-running must NOT re-do completed expensive stages.

**Two processes, one contract:**
- **Python (LangGraph)** = orchestration brain. Runs Whisper (transcription), YOLO (face detection), scene detection, caption layout. Owns state + checkpoints.
- **Node (Remotion)** = renderer. Reads a single `props.json` written by Python and renders the final MP4 frame-by-frame.
- **Contract** = `props.json` (schema in §6) + a subprocess call to `npx remotion render`.

Do not blur this boundary. Python never renders pixels; Remotion never runs ML.

---

## 1. Tech stack (use exactly these)

**Python**
- `langgraph`, `langgraph-checkpoint-sqlite` — orchestration + persistence
- `faster-whisper` — transcription with **word-level timestamps** (`word_timestamps=True`)
- `ultralytics` — YOLO face/person detection (use a face model, e.g. a YOLOv8-face weight; fall back to `person` class boxes if no face weight)
- `scenedetect` (PySceneDetect) — shot-cut detection (for pacing-aware timing)
- `opencv-python` — frame sampling
- `ffmpeg` / `ffprobe` via `subprocess` — audio extraction + media probing
- `pydantic` (optional, for validating `props.json` before writing)

**Node**
- Remotion v4: `remotion`, `@remotion/cli`, `@remotion/captions`, `@remotion/animation-utils`
- React 19
- (Do NOT add `@remotion/install-whisper-cpp` — Python already transcribed; Remotion only consumes timings.)

**System:** `ffmpeg` and Node 20+ must be on PATH.

---

## 2. Project structure (create exactly this)

```
caption-agent/
├─ pipeline/
│  ├─ __init__.py
│  ├─ state.py            # CaptionState TypedDict + dataclasses (§3)
│  ├─ templates.py        # the 4 template param dicts (§5)
│  ├─ graph.py            # build_graph(): nodes, edges, conditional edges, checkpointer (§4)
│  ├─ run.py              # CLI entrypoint + the human-in-the-loop runner (§7)
│  └─ nodes/
│     ├─ __init__.py
│     ├─ probe.py         # probe_video
│     ├─ audio.py         # extract_audio
│     ├─ transcribe.py    # transcribe
│     ├─ scenes.py        # detect_scenes
│     ├─ detect.py        # detect_regions  (YOLO)
│     ├─ safezones.py     # compute_safe_zones
│     ├─ layout.py        # layout_captions  (the "intelligent placement")
│     └─ remotion.py      # write_remotion_props + render (subprocess)
├─ remotion/
│  ├─ package.json
│  ├─ remotion.config.ts
│  └─ src/
│     ├─ index.ts         # registerRoot
│     ├─ Root.tsx         # Composition + calculateMetadata (reads props)
│     ├─ types.ts         # mirror of props.json schema (§6)
│     ├─ CaptionedVideo.tsx   # <OffthreadVideo> base + <Captions> layer
│     └─ Captions.tsx     # the 4 styles, frame-pure via useCurrentFrame (§5)
├─ data/
│  └─ checkpoints.sqlite  # created at runtime
├─ requirements.txt
└─ README.md
```

---

## 3. The State (pipeline/state.py)

This object flows through every node. Each node reads keys it needs and returns ONLY the keys it sets. Use `TypedDict` with reducers where parallel nodes write.

```python
from typing import TypedDict, Optional, Annotated
from dataclasses import dataclass
import operator

@dataclass
class Word:
    text: str
    start: float   # seconds
    end: float

@dataclass
class Scene:
    start: float
    end: float

@dataclass
class Box:
    x: float; y: float; w: float; h: float   # normalized 0..1

@dataclass
class FrameDet:
    t: float                 # timestamp (s) of sampled frame
    boxes: list[Box]         # face/person boxes at this time

@dataclass
class SafeZone:
    start: float; end: float # time window
    x: float; y: float       # normalized anchor point for caption block
    anchor: str              # "center" | "lower" | "upper"

@dataclass
class Page:
    start_ms: int
    end_ms: int
    x: float; y: float       # normalized 0..1 placement
    anchor: str
    words: list[Word]        # words on this page (ms handled at write time)

class CaptionState(TypedDict, total=False):
    # ---- inputs (set by caller) ----
    video_path: str
    template_id: str         # "punch" | "karaoke" | "flyin" | "glitch"
    output_path: str
    language: str            # e.g. "en"

    # ---- media meta (probe_video) ----
    fps: float
    duration_sec: float
    width: int
    height: int
    audio_path: str

    # ---- analysis (parallel nodes write DISJOINT keys) ----
    words: list                  # transcribe       -> list[Word]
    scenes: list                 # detect_scenes    -> list[Scene]
    detections: list             # detect_regions   -> list[FrameDet]
    safe_zones: list             # compute_safe_zones-> list[SafeZone]

    # ---- assembly ----
    pages: list                  # layout_captions  -> list[Page]
    props_path: str              # write_remotion_props
    rendered_path: str           # render

    # ---- control / observability ----
    errors: Annotated[list[str], operator.add]   # reducer: nodes append
    status: str                                  # "running"|"awaiting_render"|"done"|"failed"
```

**Rule:** because some nodes run in parallel (§4), any key written by two concurrent nodes MUST use an `Annotated[..., reducer]`. The parallel nodes here write disjoint keys (`words`, `scenes`, `detections`) so only `errors` needs the reducer.

---

## 4. The Graph (pipeline/graph.py) — FIXED topology

Build this exact DAG. There is a deliberate **parallel section** (transcription, face detection, and scene detection are independent) that **fans in** at `layout_captions`.

```
                ┌──────────────┐
   START ──────▶│ probe_video  │   (ffprobe: fps, duration, w, h)
                └──────┬───────┘
                       │
          ┌────────────┼─────────────────────────┐
          ▼            ▼                          ▼
   ┌────────────┐ ┌──────────────┐         ┌──────────────┐
   │extract_audio│ │detect_regions│         │ detect_scenes│   (parallel)
   └──────┬─────┘ └──────┬───────┘         └──────┬───────┘
          ▼              ▼                         │
   ┌────────────┐ ┌────────────────┐              │
   │ transcribe │ │compute_safe_zones│            │
   └──────┬─────┘ └──────┬─────────┘              │
          │              │                         │
          └──────────────┼─────────────────────────┘
                         ▼
                 ┌────────────────┐
                 │ layout_captions│   (fan-in: needs words + safe_zones + scenes)
                 └──────┬─────────┘
                        ▼
              ┌────────────────────┐
              │ write_remotion_props│
              └──────┬─────────────┘
                     ▼
            (interrupt_before=["render"]  ← human approves placement)
                     ▼
                ┌──────────┐
                │  render  │   (subprocess: npx remotion render)
                └────┬─────┘
                     ▼
                ┌──────────┐
                │ finalize │ → END
                └──────────┘
```

### Edges to add
```python
from langgraph.graph import StateGraph, START, END
from langgraph.pregel import RetryPolicy
from langgraph.checkpoint.sqlite import SqliteSaver

g = StateGraph(CaptionState)

g.add_node("probe_video", probe_video)
g.add_node("extract_audio", extract_audio)
g.add_node("transcribe", transcribe, retry=RetryPolicy(max_attempts=3))
g.add_node("detect_scenes", detect_scenes, retry=RetryPolicy(max_attempts=2))
g.add_node("detect_regions", detect_regions, retry=RetryPolicy(max_attempts=2))
g.add_node("compute_safe_zones", compute_safe_zones)
g.add_node("layout_captions", layout_captions)
g.add_node("write_remotion_props", write_remotion_props)
g.add_node("render", render, retry=RetryPolicy(max_attempts=2))
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
g.add_edge("transcribe", "layout_captions")
g.add_edge("compute_safe_zones", "layout_captions")
g.add_edge("detect_scenes", "layout_captions")
# tail
g.add_edge("layout_captions", "write_remotion_props")
g.add_edge("write_remotion_props", "render")
g.add_edge("render", "finalize")
g.add_edge("finalize", END)
```

### Conditional edge (graceful abort) — add one real router
After `transcribe`, if no words were produced, abort gracefully instead of rendering an empty video:
```python
def route_after_transcribe(state):
    if not state.get("words"):
        return "finalize"          # nothing to caption -> short-circuit
    return "layout_captions"

# replace the plain edge from transcribe with:
g.add_conditional_edges("transcribe", route_after_transcribe,
                        {"layout_captions": "layout_captions", "finalize": "finalize"})
```
> `RetryPolicy` handles transient failures (network/GPU hiccups). The conditional edge handles *logical* dead-ends. Use both — that's the "proper" pattern.

### Checkpointer + compile (this is the resumability core)
```python
def build_graph(db_path="data/checkpoints.sqlite"):
    saver = SqliteSaver.from_conn_string(db_path)   # persists every super-step
    return g.compile(
        checkpointer=saver,
        interrupt_before=["render"],   # pause so the user can approve placement
    )
```
- Every node's output is checkpointed to SQLite, keyed by `thread_id`.
- Re-invoking with the **same `thread_id`** resumes from the last completed node — completed stages are NOT recomputed.
- `interrupt_before=["render"]` stops the graph right before the expensive render so a human (or a UI) can inspect `pages` and approve. Resume by invoking again with `None` as input on the same thread.

---

## 5. The four templates (pipeline/templates.py) + Remotion rendering (Captions.tsx)

These are the SAME four styles from the working prototype. Port the param objects to Python (they get written into `props.json`) and port the animation logic to `Captions.tsx`.

```python
TEMPLATES = {
  "punch":   {"font":"Anton",        "sizePx":46, "weight":400, "upper":True,
              "perPage":3, "anim":"pop",    "baseColor":"#ffffff",
              "activeColor":"#d8ff3e", "enterMs":320, "defaultPosY":0.62},
  "karaoke": {"font":"Archivo",      "sizePx":30, "weight":900, "upper":False,
              "perPage":5, "anim":"fill",   "baseColor":"rgba(255,255,255,.55)",
              "activeColor":"#46e8ff", "enterMs":320, "defaultPosY":0.78},
  "flyin":   {"font":"Archivo Black","sizePx":38, "weight":400, "upper":False,
              "perPage":3, "anim":"fly",    "baseColor":"#ffffff",
              "activeColor":"#ff4d8d", "enterMs":320, "defaultPosY":0.50},
  "glitch":  {"font":"JetBrains Mono","sizePx":30,"weight":800, "upper":True,
              "perPage":2, "anim":"glitch", "baseColor":"#eafff0",
              "activeColor":"#7fffa0", "enterMs":320, "defaultPosY":0.40},
}
```

**Captions.tsx — render every word as a pure function of `useCurrentFrame()`** (so the timeline is deterministic and reversible, exactly like the prototype). For each page active at the current frame, lay out its words; for each word compute `enterProgress` from `(frameMs - word.startMs)` and `active = startMs <= frameMs <= endMs`, then per `anim`:

- **pop**: scale `0.55 → 1` with an overshoot (back-ease) on entry; active word switches to `activeColor` and gets a small scale kick.
- **fill** (karaoke): word slides up + fades in; the active word's color is filled left→right via a `linear-gradient` + `background-clip:text`, fill % = `(frameMs - startMs)/(endMs - startMs)`.
- **fly**: word enters from an alternating offset `translate + rotate` easing to 0; vary `fontSize` per word index (`×1`, `×1.28`, `×0.82`) for mixed sizes.
- **glitch**: chromatic split via two-color `text-shadow` whose offset decays with `enterProgress`; small sine jitter while active.

Use `interpolate()` and `spring()` from `remotion` for the easing. Position the page block at the props-provided normalized `(x, y)` with the given `anchor`.

---

## 6. The contract: props.json schema (Python writes → Remotion reads)

`write_remotion_props` serializes state into this exact shape. `types.ts` mirrors it. Times are **milliseconds**; positions are **normalized 0..1**.

```jsonc
{
  "videoSrc": "absolute/or/staticFile/path/to/input.mp4",
  "fps": 30,
  "width": 1080,
  "height": 1920,
  "durationInFrames": 5400,
  "template": {
    "id": "punch",
    "font": "Anton",
    "sizePx": 46,
    "weight": 400,
    "upper": true,
    "anim": "pop",
    "baseColor": "#ffffff",
    "activeColor": "#d8ff3e",
    "enterMs": 320
  },
  "pages": [
    {
      "startMs": 250,
      "endMs": 1840,
      "x": 0.5,            // normalized anchor
      "y": 0.62,
      "anchor": "lower",
      "words": [
        { "text": "This", "startMs": 250, "endMs": 560 },
        { "text": "is",   "startMs": 630, "endMs": 820 },
        { "text": "huge", "startMs": 890, "endMs": 1840 }
      ]
    }
  ]
}
```

`Root.tsx` uses `calculateMetadata` to read `fps`, `width`, `height`, `durationInFrames` from input props so the composition sizes itself to the source video. Base layer = `<OffthreadVideo src={videoSrc} />`; caption layer = `<Captions pages={pages} template={template} fps={fps} />`.

---

## 7. Node behavior spec (one paragraph each — implement faithfully)

- **probe_video** — `ffprobe` the input; set `fps`, `duration_sec`, `width`, `height`. No ML.
- **extract_audio** — `ffmpeg -i video -ac 1 -ar 16000 audio.wav`; set `audio_path`.
- **transcribe** — `faster-whisper` (`model="base"` or `"small"`, `word_timestamps=True`, language from state). Flatten segments → `list[Word]` (one per word, seconds). Set `words`.
- **detect_scenes** — PySceneDetect `ContentDetector` on the video → `list[Scene]` with start/end seconds. Set `scenes`. (Used later only to bias caption timing/pacing; safe to leave minimal in v1.)
- **detect_regions** — sample frames at **2 fps** with OpenCV; run YOLO face model per sampled frame; normalize boxes to 0..1; set `detections` = `list[FrameDet]`.
- **compute_safe_zones** — heuristic v1: for each rolling time window (align to scene or fixed 1.5s), take the **union of all face boxes** in that window (pad each box ~8%). Test three candidate anchors — lower-third `(0.5, 0.80)`, upper-third `(0.5, 0.20)`, center `(0.5, 0.5)` — and choose the one whose caption band has **least overlap** with the union; default to lower-third on ties or when no faces. Emit `list[SafeZone]`.
- **layout_captions** — group `words` into pages of `template.perPage` (break early on sentence-final punctuation). For each page, find the `SafeZone` covering its time span and copy its `(x, y, anchor)`; fall back to `template.defaultPosY` if none. Emit `list[Page]`.
- **write_remotion_props** — build the §6 dict (convert seconds→ms), validate, write `remotion/public/props.json` (so Remotion can `staticFile` it) and set `props_path`. Copy/symlink the input video into `remotion/public/` too.
- **render** — `subprocess.run(["npx","remotion","render","src/index.ts","CaptionedVideo", output_path, "--props=./public/props.json", "--concurrency=2"], cwd="remotion", check=True)`. Set `rendered_path`. Raise on non-zero exit (RetryPolicy will retry).
- **finalize** — verify `rendered_path` exists and non-empty; set `status="done"`. If reached via the empty-transcript route, set `status="failed"` with an explanatory error.

---

## 8. CLI + human-in-the-loop runner (pipeline/run.py)

```python
# python -m pipeline.run --video in.mp4 --template punch --out out.mp4 --thread job-001
```
Behavior:
1. Build the graph; config = `{"configurable": {"thread_id": args.thread}}`.
2. `app.invoke(initial_state, config)` — runs until the `render` interrupt.
3. Print the planned `pages` (text + position + anchor) so the user can sanity-check placement.
4. Prompt: `Approve and render? [y/n]`. On `y`: `app.invoke(None, config)` resumes through `render`→`finalize`. On `n`: exit, leaving the checkpoint intact so they can resume later with the same `--thread`.
5. Demonstrate resumability in the README: kill the process during render, re-run the same command with the same `--thread`, show it skips straight back to render.

---

## 9. Acceptance criteria (the build is done when ALL pass)

1. `python -m pipeline.run --video sample.mp4 --template punch --out out.mp4 --thread t1` produces `out.mp4` with animated captions burned in.
2. Captions visibly avoid the speaker's face (sit in lower-third when a centered face is present).
3. Switching `--template` to `karaoke|flyin|glitch` changes the animation with no other code changes.
4. Re-running with `--thread t1` after a completed transcription does NOT re-transcribe (verify via a log line or timing).
5. The `interrupt_before=["render"]` pause fires and prints placement before any rendering happens.
6. `props.json` validates against `types.ts` (no shape drift between Python and Remotion).

---

## 10. Build order (do not parallelize the build itself)

1. Scaffold both folders + `requirements.txt` + `package.json`; get `npx remotion studio` running on a hardcoded `props.json` with one page. (Prove the renderer first.)
2. Implement `Captions.tsx` with all four styles against that static props file until they look right in Studio.
3. Implement `state.py`, `templates.py`, and the trivial nodes (`probe`, `audio`).
4. Implement `transcribe` → feed real word timings into props → confirm sync in Studio.
5. Implement `detect_regions` + `compute_safe_zones` + `layout_captions` → confirm captions dodge faces.
6. Wire `graph.py` with the exact topology + checkpointer + interrupt; implement `run.py`.
7. Add `detect_scenes` last (pacing polish).
8. Verify all acceptance criteria.

Start at step 1 now. Ask me before changing the State schema, the graph topology, or the props.json contract — everything else is yours to implement.
