"""Guarantee a test asset at assets/sample.mp4 (MASTER_PROMPT §2).

Fallback chain:
  1. assets/sample.mp4 already exists  -> use it.
  2. webcam capture (opt-in: CAPTION_AGENT_WEBCAM=1) -> record ~8s.
     The exact per-OS command is always printed so you can run it by hand.
  3. synthetic talking clip via pyttsx3 (offline TTS) muxed over an ffmpeg
     background. This clip is FACELESS: it can validate captions/sync/contract
     (Criteria 1,3,4,6) but NOT face-avoidance (Criterion 2).

Prints which branch was used.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
SAMPLE = ASSETS / "sample.mp4"
VOICE = ASSETS / "voice.wav"

W, H, DUR = 720, 1280, 8


def _ffprobe_duration(path: Path) -> float:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(path)],
            capture_output=True, text=True, check=True,
        )
        return float(out.stdout.strip())
    except Exception:
        return float(DUR)


def _print_webcam_command() -> None:
    plat = sys.platform
    print("\n  To record a real-face clip yourself (~8s), run ONE of:")
    if plat.startswith("win"):
        print('   # list devices:  ffmpeg -list_devices true -f dshow -i dummy')
        print('   ffmpeg -y -f dshow -i video="<YOUR_CAM>":audio="<YOUR_MIC>" '
              f'-t {DUR} "{SAMPLE}"')
    elif plat == "darwin":
        print(f'   ffmpeg -y -f avfoundation -i "0:0" -t {DUR} "{SAMPLE}"')
    else:
        print('   ffmpeg -y -f v4l2 -i /dev/video0 -f alsa -i default '
              f'-t {DUR} "{SAMPLE}"')
    print()


def branch_existing() -> bool:
    if SAMPLE.exists() and SAMPLE.stat().st_size > 1000:
        print(f"[ensure_sample] BRANCH 1: using existing asset {SAMPLE} "
              f"({SAMPLE.stat().st_size} bytes)")
        return True
    return False


def branch_webcam() -> bool:
    _print_webcam_command()
    if os.environ.get("CAPTION_AGENT_WEBCAM") != "1":
        print("[ensure_sample] BRANCH 2 skipped (set CAPTION_AGENT_WEBCAM=1 to "
              "auto-record from the default device).")
        return False
    plat = sys.platform
    if plat.startswith("win"):
        cam = os.environ.get("CAPTION_AGENT_CAM", "Integrated Camera")
        mic = os.environ.get("CAPTION_AGENT_MIC", "Microphone Array")
        cmd = ["ffmpeg", "-y", "-f", "dshow",
               "-i", f"video={cam}:audio={mic}", "-t", str(DUR), str(SAMPLE)]
    elif plat == "darwin":
        cmd = ["ffmpeg", "-y", "-f", "avfoundation", "-i", "0:0",
               "-t", str(DUR), str(SAMPLE)]
    else:
        cmd = ["ffmpeg", "-y", "-f", "v4l2", "-i", "/dev/video0",
               "-f", "alsa", "-i", "default", "-t", str(DUR), str(SAMPLE)]
    try:
        subprocess.run(cmd, check=True, timeout=DUR + 20)
        print(f"[ensure_sample] BRANCH 2: recorded webcam -> {SAMPLE}")
        return SAMPLE.exists()
    except Exception as exc:  # noqa: BLE001
        print(f"[ensure_sample] BRANCH 2 webcam capture failed: {exc}")
        return False


def branch_synthetic() -> bool:
    ASSETS.mkdir(parents=True, exist_ok=True)
    text = ("Hey there. This is a synthetic test clip for the caption pipeline. "
            "Watch the words pop on screen exactly as I speak them.")
    try:
        import pyttsx3
        engine = pyttsx3.init()
        engine.setProperty("rate", 165)
        engine.save_to_file(text, str(VOICE))
        engine.runAndWait()
    except Exception as exc:  # noqa: BLE001
        print(f"[ensure_sample] pyttsx3 TTS failed ({exc}); using a silent tone.")

    dur = _ffprobe_duration(VOICE) if VOICE.exists() else float(DUR)
    dur = max(4.0, min(dur + 0.4, 20.0))

    bg = (f"color=c=0x101826:s={W}x{H}:r=30,"
          "drawtext=text='SYNTHETIC CLIP — NO FACE':fontcolor=white:fontsize=34:"
          "x=(w-text_w)/2:y=120,"
          "drawtext=text='(drop a real selfie at assets/sample.mp4)':"
          "fontcolor=0x8aa0c0:fontsize=24:x=(w-text_w)/2:y=170")

    if VOICE.exists():
        cmd = ["ffmpeg", "-y",
               "-f", "lavfi", "-i", bg,
               "-i", str(VOICE),
               "-t", f"{dur:.2f}", "-c:v", "libx264", "-pix_fmt", "yuv420p",
               "-c:a", "aac", "-shortest", str(SAMPLE)]
    else:  # no TTS -> fall back to a tone so the file is still valid
        cmd = ["ffmpeg", "-y",
               "-f", "lavfi", "-i", bg,
               "-f", "lavfi", "-i", "sine=frequency=220:duration=" + str(dur),
               "-t", f"{dur:.2f}", "-c:v", "libx264", "-pix_fmt", "yuv420p",
               "-c:a", "aac", "-shortest", str(SAMPLE)]

    subprocess.run(cmd, capture_output=True, text=True, check=True)
    print(f"[ensure_sample] BRANCH 3: built synthetic clip -> {SAMPLE} "
          f"({dur:.1f}s)")
    print("\n  " + "!" * 68)
    print("  WARNING: this clip has NO FACE. Criterion 2 (face-avoidance) CANNOT")
    print("  be validated on it and will be WARN+SKIPPED. Drop a real talking-head")
    print(f"  selfie at {SAMPLE} to fully verify face dodging.")
    print("  " + "!" * 68 + "\n")
    return True


def main() -> int:
    if not shutil.which("ffmpeg"):
        print("error: ffmpeg not on PATH", file=sys.stderr)
        return 2
    if branch_existing():
        return 0
    if branch_webcam():
        return 0
    branch_synthetic()
    return 0


if __name__ == "__main__":
    sys.exit(main())
