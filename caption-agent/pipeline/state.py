"""CaptionState + dataclasses (MASTER_PROMPT §3).

This object flows through every node. Each node reads the keys it needs and
returns ONLY the keys it sets. Keys written by concurrent nodes must use an
``Annotated[..., reducer]``; here the parallel branch writes disjoint keys
(``words``, ``scenes``, ``detections``) so only ``errors`` needs the reducer.
"""

from typing import TypedDict, Annotated
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
    x: float
    y: float
    w: float
    h: float   # normalized 0..1


@dataclass
class FrameDet:
    t: float                 # timestamp (s) of sampled frame
    boxes: list[Box]         # face/person boxes at this time


@dataclass
class SafeZone:
    start: float
    end: float               # time window
    x: float
    y: float                 # normalized anchor point for caption block
    anchor: str              # "center" | "lower" | "upper"


@dataclass
class Page:
    start_ms: int
    end_ms: int
    x: float
    y: float                 # normalized 0..1 placement
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
    words: list                  # transcribe        -> list[Word]
    scenes: list                 # detect_scenes     -> list[Scene]
    detections: list             # detect_regions    -> list[FrameDet]
    safe_zones: list             # compute_safe_zones -> list[SafeZone]

    # ---- assembly ----
    pages: list                  # layout_captions   -> list[Page]
    props_path: str              # write_remotion_props
    rendered_path: str           # render

    # ---- control / observability ----
    errors: Annotated[list[str], operator.add]   # reducer: nodes append
    status: str                                  # "running"|"awaiting_render"|"done"|"failed"
