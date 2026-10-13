"""Pipeline node functions. Each reads keys it needs and returns only what it sets."""

from .probe import probe_video
from .audio import extract_audio
from .transcribe import transcribe
from .scenes import detect_scenes
from .detect import detect_regions
from .safezones import compute_safe_zones
from .layout import layout_captions
from .remotion import write_remotion_props, render, finalize

__all__ = [
    "probe_video",
    "extract_audio",
    "transcribe",
    "detect_scenes",
    "detect_regions",
    "compute_safe_zones",
    "layout_captions",
    "write_remotion_props",
    "render",
    "finalize",
]
