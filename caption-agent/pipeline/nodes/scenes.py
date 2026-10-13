"""detect_scenes — PySceneDetect ContentDetector -> list[Scene] (pacing polish)."""

from ..state import CaptionState, Scene
from ._log import log


def detect_scenes(state: CaptionState) -> dict:
    video = state["video_path"]
    duration = float(state.get("duration_sec") or 0.0)

    # Lazy import; keep this minimal in v1 (used only to bias timing later).
    from scenedetect import detect, ContentDetector

    try:
        scene_list = detect(video, ContentDetector())
    except Exception as exc:  # noqa: BLE001 - degrade to a single scene
        log("scenes", f"detector failed ({exc}); using single scene")
        scene_list = []

    scenes = [
        Scene(start=start.get_seconds(), end=end.get_seconds())
        for (start, end) in scene_list
    ]
    if not scenes:
        scenes = [Scene(start=0.0, end=duration)]

    log("scenes", f"{len(scenes)} scene(s)")
    return {"scenes": scenes}
