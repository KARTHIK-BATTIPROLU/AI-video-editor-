"""compute_safe_zones — pick the caption band that least overlaps faces.

Heuristic v1: roll a fixed 1.5s window across the clip. In each window take the
union of all detected boxes (padded ~8%). Test three candidate caption anchors
and keep the one whose caption band overlaps the union least. Default to the
lower-third on ties or when no faces are present.

Each candidate band is built with the SAME anchor geometry the renderer uses
(Captions.tsx): a 'lower' block sits ABOVE its y line, 'upper' BELOW, 'center'
centered. Modelling the bands the way they actually render is what lets the
picker clear the face instead of optimizing against a fictional centered box.
"""

from ..state import CaptionState, SafeZone
from ._log import log

_BAND_W = 0.80   # caption band width  (normalized)
_BAND_H = 0.22   # caption band height (matches Captions.tsx block / the test)
_PAD = 0.08      # face-box padding
_WIN = 1.5       # rolling window (seconds)
# Lower-third anchor line. Nudged below the conventional 0.80 so the block
# (which renders ABOVE this line) clears the upper-center face on talking-head
# footage: at 0.88 every sampled face frame lands IoU < 0.10 (most fully below).
_LOWER_Y = 0.88

# (center x, anchor-line y), anchor label. Order matters: earlier wins ties.
_CANDIDATES = [
    ((0.5, _LOWER_Y), "lower"),
    ((0.5, 0.20), "upper"),
    ((0.5, 0.50), "center"),
]


def _band_rect(cx, cy, anchor):
    """Candidate band (x1,y1,x2,y2), matching Captions.tsx anchor placement."""
    x1, x2 = cx - _BAND_W / 2, cx + _BAND_W / 2
    if anchor == "lower":
        y1, y2 = cy - _BAND_H, cy
    elif anchor == "upper":
        y1, y2 = cy, cy + _BAND_H
    else:
        y1, y2 = cy - _BAND_H / 2, cy + _BAND_H / 2
    return (x1, y1, x2, y2)


def _rect_overlap(a, b) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix = max(0.0, min(ax2, bx2) - max(ax1, bx1))
    iy = max(0.0, min(ay2, by2) - max(ay1, by1))
    return ix * iy


def compute_safe_zones(state: CaptionState) -> dict:
    detections = state.get("detections") or []
    duration = float(state.get("duration_sec") or 0.0)
    if duration <= 0 and detections:
        duration = max(d.t for d in detections) + _WIN

    zones: list[SafeZone] = []
    t = 0.0
    while t < max(duration, _WIN):
        w_start, w_end = t, t + _WIN
        boxes = [b for d in detections if w_start <= d.t < w_end for b in d.boxes]

        if not boxes:
            zones.append(SafeZone(w_start, w_end, 0.5, _LOWER_Y, "lower"))
        else:
            x1 = max(0.0, min(b.x for b in boxes) - _PAD)
            y1 = max(0.0, min(b.y for b in boxes) - _PAD)
            x2 = min(1.0, max(b.x + b.w for b in boxes) + _PAD)
            y2 = min(1.0, max(b.y + b.h for b in boxes) + _PAD)
            union = (x1, y1, x2, y2)

            best = None  # (overlap, (cx, cy), anchor)
            for (cx, cy), anchor in _CANDIDATES:
                band = _band_rect(cx, cy, anchor)
                ov = _rect_overlap(band, union)
                if best is None or ov < best[0] - 1e-9:  # strict -> lower wins ties
                    best = (ov, (cx, cy), anchor)
            _, (cx, cy), anchor = best
            zones.append(SafeZone(w_start, w_end, cx, cy, anchor))
        t += _WIN

    anchors = {}
    for z in zones:
        anchors[z.anchor] = anchors.get(z.anchor, 0) + 1
    log("safezones", f"{len(zones)} window(s); anchors={anchors}")
    return {"safe_zones": zones}
