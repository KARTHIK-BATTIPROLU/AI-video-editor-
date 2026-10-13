# caption-agent

A **stateful, resumable video-editing pipeline** that burns animated, word-synced
captions into a talking-head video and **positions them to avoid faces**. Pick one
of four caption styles; the pipeline transcribes, detects faces, finds safe zones,
lays out captions, and renders the final MP4.

Two processes, one contract:

| Process | Role | Tech |
|---|---|---|
| **Python (LangGraph)** | orchestration brain — transcription, face detection, scene detection, caption layout, state + checkpoints | `langgraph`, `faster-whisper`, `ultralytics` (YOLO), `scenedetect`, `opencv`, `ffmpeg` |
| **Node (Remotion)** | renderer — reads one `props.json` and renders frame-by-frame | `remotion` v4, React 19, `@remotion/google-fonts` |

The contract between them is **`remotion/public/props.json`** (schema below). Python
never renders pixels; Remotion never runs ML.

```
START → probe_video ─┬─ extract_audio → transcribe ─┐ (conditional: empty → finalize)
                     ├─ detect_regions → compute_safe_zones ─┤
                     └─ detect_scenes ─────────────────────────┤
                                                               ▼
                                                  layout_captions  (barrier fan-in)
                                                               ▼
                                                  write_remotion_props
                                                               ▼
                                          ⏸ interrupt_before=["render"]  (human approves)
                                                               ▼
                                                     render → finalize → END
```

---

## Prerequisites

- **Python 3.11+**, **Node 20+**, and **ffmpeg/ffprobe** on `PATH`.
- First Remotion render downloads a headless Chromium automatically.
- Google Fonts are fetched at render time (network needed once; they cache).

## Setup

```powershell
# 1) Node / Remotion renderer
cd caption-agent\remotion
npm install

# 2) Python orchestrator (isolated venv recommended)
cd ..
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

> `requirements.txt` pulls the full stack including `ultralytics` (YOLO), which
> installs PyTorch (~2 GB). To run **without** YOLO (captions default to the
> lower-third instead of actively dodging faces), skip that line or set
> `CAPTION_AGENT_NO_YOLO=1`. `faster-whisper` is PyTorch-free (CTranslate2).

## Usage

```powershell
.\.venv\Scripts\python.exe -m pipeline.run `
  --video sample.mp4 --template punch --out out.mp4 --thread t1
```

The pipeline runs up to the **render interrupt**, prints the planned placement, and
asks `Approve and render? [y/n]`. On `y` it resumes through `render → finalize`.
Use `--yes` to auto-approve (for scripted runs).

| flag | meaning |
|---|---|
| `--video` | input video path |
| `--template` | `punch` \| `karaoke` \| `flyin` \| `glitch` |
| `--out` | output mp4 path |
| `--thread` | checkpoint id — **reuse it to resume** |
| `--language` | transcription hint (default `en`) |
| `--yes` | skip the y/n approval prompt |

### The four styles

| id | font | animation |
|---|---|---|
| `punch` | Anton | scale pop w/ overshoot; active word turns lime |
| `karaoke` | Archivo | slides up; active word fills left→right (gradient clip) |
| `flyin` | Archivo Black | words fly in from alternating angles, mixed sizes |
| `glitch` | JetBrains Mono | chromatic split that decays on entry + sine jitter |

Switching `--template` is the *only* change needed — no code edits.

## Resumability (the checkpoint core)

Every node's output is checkpointed to `data/checkpoints.sqlite`, keyed by
`thread_id`. Re-invoking with the **same `--thread`** resumes from the last
completed node — finished, expensive stages (transcription, detection) are **not**
recomputed.

```powershell
# Start a job; kill it (Ctrl-C) during the render…
.\.venv\Scripts\python.exe -m pipeline.run --video sample.mp4 --template punch --out out.mp4 --thread t1
# …re-run the SAME command: it skips straight back to the render gate.
.\.venv\Scripts\python.exe -m pipeline.run --video sample.mp4 --template punch --out out.mp4 --thread t1
```

## The contract — `props.json` (Python writes → Remotion reads)

Times are **milliseconds**; positions are **normalized 0..1**. `types.ts` mirrors
this exactly and `write_remotion_props` validates it with pydantic before writing.

```jsonc
{
  "videoSrc": "input.mp4", "fps": 30, "width": 1080, "height": 1920,
  "durationInFrames": 5400,
  "template": { "id": "punch", "font": "Anton", "sizePx": 46, "weight": 400,
                "upper": true, "anim": "pop", "baseColor": "#ffffff",
                "activeColor": "#d8ff3e", "enterMs": 320 },
  "pages": [
    { "startMs": 250, "endMs": 1840, "x": 0.5, "y": 0.62, "anchor": "lower",
      "words": [ { "text": "This", "startMs": 250, "endMs": 560 } ] }
  ]
}
```

You can iterate on the renderer alone in Remotion Studio against the last
`props.json`:

```powershell
cd remotion ; npm run studio
```

## Implementation notes

- **Barrier fan-in.** `layout_captions` waits for *all three* analysis branches.
  LangGraph's default trigger is OR (a node fires as soon as the first predecessor
  lands), so the node is registered with `defer=True` to make it a true barrier.
  This is a node hint — the graph **topology (nodes + edges) is exactly §4**.
- **Conditional edge.** After `transcribe`, an empty transcript routes to
  `finalize`. Because `layout_captions` also has the safe-zones/scenes edges,
  langgraph still runs it; the tail nodes guard against this so an empty transcript
  **never renders an empty video** and ends on `status="failed"`.
- **YOLO weights.** Drop a `yolov8n-face.pt` (face model) in the project root for
  face-accurate zones; otherwise it falls back to COCO `person` boxes
  (`yolov8n.pt`, auto-downloaded).

## Verifying

**Orchestration only (no ML stack)** — exercise the real graph/CLI with fast stubs
for the heavy ML nodes; still does a real Remotion render against `sample.mp4`:

```powershell
.\.venv\Scripts\python.exe _smoke_test.py   # topology, interrupt, resume, contract, abort
.\.venv\Scripts\python.exe _cli_test.py     # run.py gate → approve → render → "already done"
```

**Real integration (no mocks)** — runs the unmocked pipeline (real faster-whisper,
real YOLO, real render) and asserts on the actual artifacts: out.mp4 is a real
video with correct dims/fps; caption pixels are burned into the band; captions
avoid the face box; `--template` visibly changes the render; same-thread resume
skips work; and a corrupted `props.json` fails both the validator and the render.

```powershell
.\.venv\Scripts\python.exe scripts\ensure_sample.py   # guarantee assets/sample.mp4
.\.venv\Scripts\python.exe _integration_test.py       # 6 real-artifact checks
```

`ensure_sample.py` uses an existing `assets/sample.mp4` if present, else records
from the webcam (opt-in `CAPTION_AGENT_WEBCAM=1`), else builds a synthetic TTS
clip. **A synthetic clip is faceless**, so the face-avoidance check WARN+SKIPs —
drop a real talking-head selfie at `assets/sample.mp4` to verify Criterion 2.

**Contract gate** — validate any `props.json` against the canonical zod schema
(`remotion/src/schema.ts`, shared by the renderer and this script):

```powershell
node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON scripts\validate_props.mjs
```

The composition also `propsSchema.parse()`s in `calculateMetadata`, so a malformed
`props.json` fails the actual render loudly (not just the studio editor).

## Project layout

```
caption-agent/
├─ pipeline/            # LangGraph orchestrator (state, templates, graph, run, nodes/)
├─ remotion/            # Remotion renderer (Root, CaptionedVideo, Captions, schema, public/)
├─ scripts/            # ensure_sample.py (asset), validate_props.mjs (contract gate)
├─ assets/sample.mp4   # test asset (yours, or synthetic from ensure_sample.py)
├─ data/checkpoints.sqlite   # created at runtime
└─ requirements.txt
```
