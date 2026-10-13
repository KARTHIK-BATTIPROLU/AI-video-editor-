"""extract_audio — ffmpeg -i video -ac 1 -ar 16000 audio.wav; set audio_path."""

import os
import subprocess

from ..state import CaptionState
from .._paths import WORK_DIR
from ._log import log


def extract_audio(state: CaptionState) -> dict:
    video = state["video_path"]
    WORK_DIR.mkdir(parents=True, exist_ok=True)

    base = os.path.splitext(os.path.basename(video))[0]
    audio_path = str(WORK_DIR / f"{base}.wav")

    cmd = [
        "ffmpeg", "-y",
        "-i", video,
        "-vn", "-ac", "1", "-ar", "16000",
        audio_path,
    ]
    subprocess.run(cmd, capture_output=True, text=True, check=True)

    log("audio", f"wrote {audio_path}")
    return {"audio_path": audio_path}
