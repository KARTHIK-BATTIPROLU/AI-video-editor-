"""REAL integration test (MASTER_PROMPT §4) — no mocks in the integration path.

Runs the unmocked pipeline (real faster-whisper, real YOLO, real Remotion render)
on assets/sample.mp4 via the CLI, then asserts on the ACTUAL artifacts:

  Check 1  out.mp4 is a real video w/ right dims/fps         (Criterion 1A)
  Check 2  captions are burned into the caption band          (Criterion 1B)
  Check 3  captions avoid the face/person box                 (Criterion 2)
  Check 4  --template visibly changes the render              (Criterion 3)
  Check 5  same-thread resume does not recompute              (Criterion 4)
  Check 6  props.json round-trips zod; corruption fails render (Criterion 6)

Guardrails: no thresholds lowered, no assertions deleted, no mocks, no fake mp4.
A check that cannot apply (no face in a synthetic sample) prints WARN+SKIP.

Run:  .venv\\Scripts\\python.exe _integration_test.py
"""

import json
import os
import subprocess
import sys
import time

import cv2
import numpy as np

# Windows consoles default to cp1252; child output (Whisper/YOLO/Remotion) and our
# own box-drawing can contain non-cp1252 bytes. Force UTF-8 everywhere we capture.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ASSET = os.path.join(HERE, "assets", "sample.mp4")
PUBLIC_PROPS = os.path.join(HERE, "remotion", "public", "props.json")
PY = sys.executable
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "base")

results = {}   # criterion -> (state, evidence)


def setres(crit, state, evidence):
    results[crit] = (state, evidence)
    print(f"  [{state}] {crit}: {evidence}")


# ----------------------------------------------------------------- helpers
def run_cli(template, out, thread, extra_env=None):
    env = dict(os.environ)
    env.update({"WHISPER_MODEL": WHISPER_MODEL, "WHISPER_DEVICE": "cpu"})
    if extra_env:
        env.update(extra_env)
    cmd = [PY, "-m", "pipeline.run", "--video", ASSET, "--template", template,
           "--out", out, "--thread", thread, "--yes"]
    t0 = time.time()
    p = subprocess.run(cmd, cwd=HERE, env=env, capture_output=True,
                       encoding="utf-8", errors="replace")
    dt = time.time() - t0
    return p.returncode, ((p.stdout or "") + "\n" + (p.stderr or "")), dt


def ffprobe(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json",
         "-show_format", "-show_streams", path],
        capture_output=True, encoding="utf-8", errors="replace", check=True)
    return json.loads(out.stdout)


def frame_at(path, t_sec):
    cap = cv2.VideoCapture(path)
    cap.set(cv2.CAP_PROP_POS_MSEC, t_sec * 1000)
    ok, f = cap.read()
    cap.release()
    assert ok, f"no frame at {t_sec:.2f}s in {path}"
    return f  # BGR ndarray


def band_rect(h, w, y_norm, anchor):
    """Pixel rect of the caption band, matching Captions.tsx anchor placement.

    In the renderer the page block is anchored at y_norm: 'lower' puts the block
    bottom on the line (text ABOVE it), 'upper' the top (text below), 'center'
    centered. The band is sized generously to contain wrapped text.
    """
    bh = int(0.22 * h)
    cy = int(y_norm * h)
    if anchor == "lower":
        y0, y1 = cy - bh, cy
    elif anchor == "upper":
        y0, y1 = cy, cy + bh
    else:
        y0, y1 = cy - bh // 2, cy + bh // 2
    y0 = max(0, y0); y1 = min(h, y1)
    x0, x1 = int(0.05 * w), int(0.95 * w)
    return y0, y1, x0, x1


def bright_mask(band):
    """Boolean mask of caption-like pixels (near-white or bright accent color).

    Templates use white/lime/cyan/pink/green text on darker video — all bright
    with >=2 high channels."""
    b, g, r = band[..., 0].astype(int), band[..., 1].astype(int), band[..., 2].astype(int)
    white = (r > 200) & (g > 200) & (b > 200)
    bright2 = ((r > 190).astype(int) + (g > 190).astype(int) + (b > 190).astype(int)) >= 2
    return white | bright2


def text_pixel_fraction(band):
    """Fraction of the band that is caption-like pixels."""
    return float(bright_mask(band).mean())


def iou(a, b):
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix = max(0, min(ax1, bx1) - max(ax0, bx0))
    iy = max(0, min(ay1, by1) - max(ay0, by0))
    inter = ix * iy
    ua = (ax1 - ax0) * (ay1 - ay0) + (bx1 - bx0) * (by1 - by0) - inter
    return inter / ua if ua > 0 else 0.0


def read_state(thread):
    """Read persisted pipeline state (pages, detections) from the checkpoint."""
    from pipeline.graph import build_graph
    from pipeline.nodes._coerce import as_page
    app = build_graph()
    vals = app.get_state({"configurable": {"thread_id": thread}}).values
    pages = [as_page(p) for p in (vals.get("pages") or [])]
    return vals, pages


def node(mjs_args):
    return subprocess.run(
        ["node", "--disable-warning=MODULE_TYPELESS_PACKAGE_JSON",
         os.path.join("scripts", "validate_props.mjs"), *mjs_args],
        cwd=HERE, capture_output=True, encoding="utf-8", errors="replace")


# ===================================================================== main
def main():
    assert os.path.exists(ASSET), f"missing {ASSET} (run scripts/ensure_sample.py)"

    out_punch = os.path.join(HERE, "out_punch.mp4")
    out_karaoke = os.path.join(HERE, "out_karaoke.mp4")
    for f in (out_punch, out_karaoke):
        if os.path.exists(f):
            os.remove(f)
    # fresh threads each run so transcription/detection actually execute
    suffix = str(int(time.time()))
    t_punch = f"itest_punch_{suffix}"
    t_karaoke = f"itest_karaoke_{suffix}"

    print(f"\n=== REAL pipeline run (punch, whisper={WHISPER_MODEL}) - no mocks ===")
    rc1, log1, dt1 = run_cli("punch", out_punch, t_punch)
    print(f"    punch run rc={rc1} in {dt1:.1f}s")
    assert rc1 == 0, f"punch CLI failed:\n{log1[-2000:]}"

    vals, pages = read_state(t_punch)
    props = json.load(open(PUBLIC_PROPS))
    src_info = ffprobe(ASSET)
    src_dur = float(src_info["format"]["duration"])

    # ---------------- Check 1: real video, right dims/fps -------------------
    print("\n[Check 1] out.mp4 is a real video with correct dims/fps")
    size = os.path.getsize(out_punch)
    info = ffprobe(out_punch)
    vstreams = [s for s in info["streams"] if s["codec_type"] == "video"]
    out_dur = float(info["format"]["duration"])
    vw = int(vstreams[0]["width"]); vh = int(vstreams[0]["height"])
    n, d = vstreams[0]["r_frame_rate"].split("/")
    out_fps = float(n) / float(d)
    frames_calc = round(out_dur * out_fps)
    c1 = (size > 30_000 and len(vstreams) >= 1
          and abs(out_dur - src_dur) <= 0.3
          and vw == props["width"] and vh == props["height"]
          and abs(frames_calc - props["durationInFrames"]) <= 2)
    setres("Criterion 1A (real video)", "PASS" if c1 else "FAIL",
           f"size={size}B dims={vw}x{vh}(props {props['width']}x{props['height']}) "
           f"dur={out_dur:.2f}s(src {src_dur:.2f}) "
           f"frames~{frames_calc} vs durInFrames={props['durationInFrames']}")

    # ---------------- Check 2: captions burned into the band ----------------
    print("\n[Check 2] caption pixels are actually burned in")
    assert pages, "no pages in state"
    # Densest page (most characters) -> a clear, non-trivial caption.
    pg = max(pages, key=lambda p: sum(len(wd.text) for wd in p.words))
    t_mid = (pg.start_ms + pg.end_ms) / 2000.0
    src_f = frame_at(ASSET, t_mid)
    out_f = frame_at(out_punch, t_mid)
    h, w = out_f.shape[:2]
    y0, y1, x0, x1 = band_rect(h, w, pg.y, pg.anchor)
    src_band = src_f[y0:y1, x0:x1]
    out_band = out_f[y0:y1, x0:x1]
    # (a) caption-like pixels must exist in the placement band
    txt_frac = text_pixel_fraction(out_band)
    # (b) those caption pixels must be REAL additions vs the source frame.
    # Measure mean-abs-diff over the caption's own bounding box (not the whole
    # band) so the wide dark margins don't average away the very signal we test.
    mask = bright_mask(out_band)
    ys, xs = np.where(mask)
    if len(xs):
        pad = 4
        ry0, ry1 = max(0, ys.min() - pad), min(out_band.shape[0], ys.max() + pad + 1)
        rx0, rx1 = max(0, xs.min() - pad), min(out_band.shape[1], xs.max() + pad + 1)
        out_txt = out_band[ry0:ry1, rx0:rx1].astype(int)
        src_txt = src_band[ry0:ry1, rx0:rx1].astype(int)
        mad = float(np.mean(np.abs(out_txt - src_txt)))
    else:
        mad = 0.0
    c2 = mad > 12 and txt_frac > 0.005
    setres("Criterion 1B (captions burned in)", "PASS" if c2 else "FAIL",
           f"t={t_mid:.2f}s '{' '.join(wd.text for wd in pg.words)}' "
           f"diff@caption={mad:.1f}(>12) text-pixels={txt_frac*100:.2f}%(>0.5%)")

    # ---------------- Check 3: captions avoid the face ----------------------
    print("\n[Check 3] captions avoid the face/person box")
    dets = vals.get("detections") or []
    total_boxes = sum(len(fd.boxes) for fd in dets)
    # find a detection near a captioned time with >=1 box
    near = None
    for fd in dets:
        if fd.boxes and any(p.start_ms / 1000 <= fd.t <= p.end_ms / 1000 for p in pages):
            near = fd; break
    if not near:
        msg = ("no face/person boxes near captions; this clip appears FACELESS "
               "(drop a real selfie at assets/sample.mp4 to verify Criterion 2)"
               if total_boxes == 0 else
               "boxes exist but none overlap a captioned time window")
        setres("Criterion 2 (avoid face)", "SKIP", msg)
    else:
        cover = next(p for p in pages if p.start_ms / 1000 <= near.t <= p.end_ms / 1000)
        # face/person box (normalized) -> pixels
        fb = near.boxes[0]
        fpx = (int(fb.x * w), int(fb.y * h), int((fb.x + fb.w) * w), int((fb.y + fb.h) * h))
        band = band_rect(h, w, cover.y, cover.anchor)
        band_xyxy = (band[2], band[0], band[3], band[1])
        ov = iou(band_xyxy, fpx)
        below = band[0] >= fpx[3]  # band top below face bottom
        c3 = ov < 0.10 or below
        setres("Criterion 2 (avoid face)", "PASS" if c3 else "FAIL",
               f"person/face box IoU={ov:.3f}(<0.10) or band-below-face={below}")

    # ---------------- Check 4: template drives the render -------------------
    print("\n=== REAL pipeline run (karaoke) - no mocks ===")
    rc2, log2, dt2 = run_cli("karaoke", out_karaoke, t_karaoke)
    print(f"    karaoke run rc={rc2} in {dt2:.1f}s")
    assert rc2 == 0, f"karaoke CLI failed:\n{log2[-2000:]}"
    print("\n[Check 4] --template visibly changes output")
    # The template ONLY affects the caption layer (font/anim/color/grouping/pos);
    # the video background is identical. So compare the caption region (lower
    # third, where both templates place text) and take the max over several
    # captioned frames — if the template reaches the renderer, at least one
    # frame's caption band differs clearly. (Whole-frame avg drowns in the
    # identical background.)
    probe = frame_at(out_punch, 2.0)
    h, w = probe.shape[:2]
    ly0, ly1, lx0, lx1 = int(0.55 * h), int(0.99 * h), int(0.02 * w), int(0.98 * w)
    best, best_t = 0.0, 0.0
    for tc in [1.5, 2.2, 2.8, 3.4, 4.0, 5.4, 6.4, 7.2]:
        try:
            pb = frame_at(out_punch, tc)[ly0:ly1, lx0:lx1]
            kb = frame_at(out_karaoke, tc)[ly0:ly1, lx0:lx1]
        except AssertionError:
            continue
        # union of caption pixels in either render: measure the diff where text
        # actually is, so identical background doesn't average the signal away.
        union = bright_mask(pb) | bright_mask(kb)
        if int(union.sum()) < 50:
            continue
        d = float(np.mean(np.abs(pb[union].astype(int) - kb[union].astype(int))))
        if d > best:
            best, best_t = d, tc
    c4 = best > 8
    setres("Criterion 3 (template switch)", "PASS" if c4 else "FAIL",
           f"punch vs karaoke caption-pixel max mean-abs-diff={best:.1f}(>8) at t={best_t:.1f}s")

    # ---------------- Check 5: resume does not recompute --------------------
    print("\n[Check 5] same-thread resume skips completed stages")
    rc3, log3, dt3 = run_cli("punch", out_punch, t_punch)  # same thread as run 1
    reran = "loading whisper" in log3.lower()
    already = "already done" in log3.lower()
    c5 = rc3 == 0 and not reran and already
    setres("Criterion 4 (resume no recompute)", "PASS" if c5 else "FAIL",
           f"2nd run {dt3:.1f}s, re-transcribed={reran}, said-already-done={already}")

    # ---------------- Check 6: contract round-trip + corruption fails -------
    print("\n[Check 6] props.json contract (zod) — valid passes, corrupt fails")
    good = node([PUBLIC_PROPS]).returncode  # validate the just-rendered props
    # corrupt a field -> standalone validator must reject
    bad = json.load(open(PUBLIC_PROPS))
    bad["template"]["anim"] = "BOGUS"; bad["fps"] = "thirty"
    bad_path = os.path.join(HERE, "out_bad_props.json")
    json.dump(bad, open(bad_path, "w"))
    bad_validator = node([bad_path]).returncode
    # corrupt props must also FAIL the actual Remotion render
    npx = "npx.cmd" if os.name == "nt" else "npx"
    rp = subprocess.run(
        [npx, "remotion", "render", "src/index.ts", "CaptionedVideo",
         os.path.join(HERE, "out_should_not_exist.mp4"),
         f"--props={bad_path}", "--frames=0-1"],
        cwd=os.path.join(HERE, "remotion"), capture_output=True,
        encoding="utf-8", errors="replace")
    render_rejected = rp.returncode != 0
    os.path.exists(os.path.join(HERE, "out_should_not_exist.mp4")) and os.remove(
        os.path.join(HERE, "out_should_not_exist.mp4"))
    os.remove(bad_path)
    c6 = good == 0 and bad_validator == 1 and render_rejected
    setres("Criterion 6 (contract round-trip)", "PASS" if c6 else "FAIL",
           f"valid→exit{good}(0) corrupt→validator exit{bad_validator}(1) "
           f"corrupt→render rejected={render_rejected}")

    # ----------------------------- summary ----------------------------------
    print("\n" + "=" * 70)
    print("CRITERION                          RESULT   EVIDENCE")
    print("-" * 70)
    any_fail = False
    for crit, (state, ev) in results.items():
        if state == "FAIL":
            any_fail = True
        print(f"{crit:34s} {state:7s}  {ev[:90]}")
    print("=" * 70)
    print("RESULT:", "FAILED" if any_fail else "ALL CRITERIA PASS (SKIPs noted)")
    return 1 if any_fail else 0


if __name__ == "__main__":
    sys.exit(main())
