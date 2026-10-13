"""write_remotion_props + render + finalize — the Python↔Remotion contract.

write_remotion_props serializes state into the §6 props.json shape (seconds→ms,
normalized positions), validates it, writes remotion/public/props.json, and
copies the input video into remotion/public/ so Remotion can staticFile() it.
render shells out to `npx remotion render`. finalize verifies the output.
"""

import json
import os
import shutil
import subprocess

from ..state import CaptionState
from ..templates import template_props
from .._paths import PUBLIC_DIR, REMOTION_DIR
from ._coerce import as_page
from ._log import log


# ---------------------------------------------------------------- validation
def _validate(props: dict) -> None:
    """Validate props against the §6 schema. No-op if pydantic isn't installed."""
    try:
        from pydantic import BaseModel, ConfigDict
    except ImportError:
        log("props", "pydantic not installed; skipping validation")
        return

    class WordModel(BaseModel):
        model_config = ConfigDict(extra="forbid")
        text: str
        startMs: int
        endMs: int

    class PageModel(BaseModel):
        model_config = ConfigDict(extra="forbid")
        startMs: int
        endMs: int
        x: float
        y: float
        anchor: str
        words: list[WordModel]

    class TemplateModel(BaseModel):
        model_config = ConfigDict(extra="forbid")
        id: str
        font: str
        sizePx: int
        weight: int
        upper: bool
        anim: str
        baseColor: str
        activeColor: str
        enterMs: int

    class PropsModel(BaseModel):
        model_config = ConfigDict(extra="forbid")
        videoSrc: str
        fps: float
        width: int
        height: int
        durationInFrames: int
        template: TemplateModel
        pages: list[PageModel]

    PropsModel(**props)  # raises on shape drift


# ----------------------------------------------------------- write the props
def write_remotion_props(state: CaptionState) -> dict:
    # Empty-transcript guard. layout_captions is a barrier fan-in (defer=True),
    # but langgraph's OR-trigger still runs it via the safe_zones/scenes edges
    # even when transcribe routed to finalize. So we must not render an empty
    # video: mark failed and write nothing. run.py treats this as a graceful
    # abort at the render gate; the render node guards too (belt and braces).
    if not state.get("words") or not (state.get("pages") or []):
        log("props", "no captions (empty transcript); marking failed, writing nothing")
        return {"status": "failed",
                "errors": ["No captions to render (empty transcript)."]}

    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)

    # Copy the source video into public/ and reference it by filename.
    video = state["video_path"]
    vname = os.path.basename(video)
    dst = PUBLIC_DIR / vname
    if os.path.abspath(video) != os.path.abspath(dst):
        shutil.copyfile(video, dst)

    fps = float(state["fps"])
    duration = float(state.get("duration_sec") or 0.0)
    duration_frames = max(1, int(round(duration * fps)))

    pages_out = []
    for p in (state.get("pages") or []):
        page = as_page(p)  # also coerces page.words to Word instances
        words_out = [
            {
                "text": w.text,
                "startMs": int(round(w.start * 1000)),
                "endMs": int(round(w.end * 1000)),
            }
            for w in page.words
        ]
        pages_out.append({
            "startMs": page.start_ms,
            "endMs": page.end_ms,
            "x": page.x,
            "y": page.y,
            "anchor": page.anchor,
            "words": words_out,
        })

    props = {
        "videoSrc": vname,
        "fps": fps,
        "width": int(state["width"]),
        "height": int(state["height"]),
        "durationInFrames": duration_frames,
        "template": template_props(state["template_id"]),
        "pages": pages_out,
    }

    _validate(props)

    props_path = PUBLIC_DIR / "props.json"
    with open(props_path, "w", encoding="utf-8") as f:
        json.dump(props, f, indent=2)

    log("props", f"wrote {props_path} ({len(pages_out)} page(s), {duration_frames} frames)")
    return {"props_path": str(props_path), "status": "awaiting_render"}


# --------------------------------------------------------------------- render
def render(state: CaptionState) -> dict:
    # Belt-and-braces: never render an empty caption set, even if forced past the gate.
    if not (state.get("pages") or []):
        log("render", "no caption pages; skipping render (empty transcript)")
        return {"status": "failed", "errors": ["Skipped render: no caption pages."]}

    output = os.path.abspath(state["output_path"])
    os.makedirs(os.path.dirname(output) or ".", exist_ok=True)

    npx = "npx.cmd" if os.name == "nt" else "npx"
    base = [
        npx, "remotion", "render", "src/index.ts", "CaptionedVideo",
        output, "--props=./public/props.json",
    ]

    # Concurrency: Remotion aborts if concurrency exceeds the cores Node sees,
    # and a Python-spawned Node can observe fewer cores than its parent (CPU
    # affinity) -- here it sees just 1. remotion.config.ts also pins
    # setConcurrency(2), which the CLI flag overrides. Default to 1 (valid on
    # any core count); users on a multi-core box can raise it via the env var.
    conc = os.environ.get("CAPTION_AGENT_CONCURRENCY", "1")
    base.append(f"--concurrency={conc}")

    # GL backend fallback chain. A forced backend can be pinned via CAPTION_AGENT_GL;
    # otherwise try the default, then ANGLE, then SwiftShader (software) — the usual
    # fixes when a headless/server GPU can't create a context.
    forced = os.environ.get("CAPTION_AGENT_GL")
    gl_attempts = [f"--gl={forced}"] if forced else [None, "--gl=angle", "--gl=swiftshader"]

    last_exc = None
    for i, gl in enumerate(gl_attempts):
        cmd = base + ([gl] if gl else [])
        log("render", f"attempt {i + 1}/{len(gl_attempts)}: $ {' '.join(cmd)} (cwd={REMOTION_DIR})")
        try:
            subprocess.run(cmd, cwd=str(REMOTION_DIR), check=True)
            log("render", f"wrote {output}")
            return {"rendered_path": output}
        except subprocess.CalledProcessError as exc:
            last_exc = exc
            log("render", f"attempt {i + 1} failed (exit {exc.returncode}); "
                          f"{'retrying with next GL backend' if i + 1 < len(gl_attempts) else 'no fallbacks left'}")
    raise last_exc  # let RetryPolicy see the failure


# ------------------------------------------------------------------- finalize
def finalize(state: CaptionState) -> dict:
    # Reached via the empty-transcript short-circuit?
    if not state.get("words"):
        log("finalize", "no words transcribed; nothing to caption")
        return {
            "status": "failed",
            "errors": ["Empty transcript: nothing to caption (short-circuited)."],
        }

    rendered = state.get("rendered_path")
    if rendered and os.path.exists(rendered) and os.path.getsize(rendered) > 0:
        log("finalize", f"done -> {rendered}")
        return {"status": "done"}

    log("finalize", "render output missing or empty")
    return {
        "status": "failed",
        "errors": ["Render output missing or empty."],
    }
