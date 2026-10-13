"""Exercise the run.py CLI path end-to-end with stubbed ML nodes (karaoke style)."""

import os
import pipeline.graph as G
from pipeline.state import Word, Scene, FrameDet, Box
from pipeline import run as runmod

HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLE = os.path.join(HERE, "remotion", "public", "sample.mp4")
OUT = os.path.join(HERE, "out_cli.mp4")

G.transcribe = lambda s: {"words": [
    Word("Switching", 0.20, 0.70), Word("templates", 0.75, 1.30),
    Word("is", 1.35, 1.55), Word("one", 1.60, 1.85), Word("flag.", 1.90, 2.60),
]}
G.detect_regions = lambda s: {"detections": [
    FrameDet(t=i * 0.5, boxes=[Box(0.30, 0.22, 0.40, 0.34)]) for i in range(8)
]}
G.detect_scenes = lambda s: {"scenes": [Scene(0.0, 6.0)]}

if os.path.exists(os.path.join(HERE, "data", "checkpoints.sqlite")):
    os.remove(os.path.join(HERE, "data", "checkpoints.sqlite"))
if os.path.exists(OUT):
    os.remove(OUT)

args = ["--video", SAMPLE, "--template", "karaoke", "--out", OUT,
        "--thread", "cli-1", "--yes"]

print("\n===== first run (fresh -> gate -> auto-approve -> render) =====")
rc1 = runmod.main(args)
print("rc1 =", rc1, "| out exists:", os.path.exists(OUT))

print("\n===== second run (same thread -> already done) =====")
rc2 = runmod.main(args)
print("rc2 =", rc2)

# Confirm template switch actually changed the props anim to 'fill'.
import json
props = json.load(open(os.path.join(HERE, "remotion", "public", "props.json")))
print("props template:", props["template"]["id"], "/", props["template"]["anim"])
ok = (rc1 == 0 and rc2 == 0 and os.path.exists(OUT)
      and props["template"]["anim"] == "fill")
print("\n" + ("CLI TEST PASSED" if ok else "CLI TEST FAILED"))
raise SystemExit(0 if ok else 1)
