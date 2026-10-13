"""probe_video — ffprobe the input; set fps, duration, width, height. No ML."""

import json
import subprocess

from ..state import CaptionState
from ._log import log


def _ffprobe(video_path: str) -> dict:
    cmd = [
        "ffprobe", "-v", "error",
        "-print_format", "json",
        "-show_streams", "-show_format",
        video_path,
    ]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def probe_video(state: CaptionState) -> dict:
    video = state["video_path"]
    info = _ffprobe(video)

    vstream = next(s for s in info["streams"] if s.get("codec_type") == "video")

    # r_frame_rate is like "30000/1001" or "30/1".
    num, _, den = vstream.get("r_frame_rate", "30/1").partition("/")
    den_f = float(den) if den else 1.0
    fps = float(num) / den_f if den_f else float(num)

    width = int(vstream["width"])
    height = int(vstream["height"])
    duration = float(
        info.get("format", {}).get("duration")
        or vstream.get("duration")
        or 0.0
    )

    log("probe", f"{width}x{height} @ {fps:.3f}fps, {duration:.2f}s")
    return {
        "fps": fps,
        "width": width,
        "height": height,
        "duration_sec": duration,
        "status": "running",
    }
