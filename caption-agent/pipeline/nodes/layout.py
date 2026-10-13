"""layout_captions — group words into pages and place each in a safe zone.

Pages hold up to ``template.perPage`` words and break early on sentence-final
punctuation. Each page copies (x, y, anchor) from the SafeZone covering its time
span, falling back to the template's defaultPosY when none applies.
"""

from ..state import CaptionState, Page
from ..templates import TEMPLATES
from ._coerce import as_word, as_safezone
from ._log import log

_SENT_FINAL = (".", "!", "?", "…")


def _zone_for(zones, start: float, end: float):
    """SafeZone with the most temporal overlap with [start, end], or None."""
    best = None
    for z in zones:
        ov = max(0.0, min(z.end, end) - max(z.start, start))
        if ov > 0 and (best is None or ov > best[0]):
            best = (ov, z)
    return best[1] if best else None


def layout_captions(state: CaptionState) -> dict:
    words = [as_word(w) for w in (state.get("words") or [])]
    zones = [as_safezone(z) for z in (state.get("safe_zones") or [])]

    tmpl = TEMPLATES[state["template_id"]]
    per_page = int(tmpl["perPage"])
    default_y = float(tmpl["defaultPosY"])

    # 1) group words into pages
    groups: list[list] = []
    cur: list = []
    for w in words:
        cur.append(w)
        ends_sentence = w.text.rstrip().endswith(_SENT_FINAL)
        if len(cur) >= per_page or ends_sentence:
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)

    # 2) place each page
    pages: list[Page] = []
    for grp in groups:
        start, end = grp[0].start, grp[-1].end
        zone = _zone_for(zones, start, end)
        if zone is not None:
            x, y, anchor = zone.x, zone.y, zone.anchor
        else:
            x, y, anchor = 0.5, default_y, "lower"
        pages.append(
            Page(
                start_ms=int(round(start * 1000)),
                end_ms=int(round(end * 1000)),
                x=x, y=y, anchor=anchor,
                words=grp,
            )
        )

    log("layout", f"{len(words)} words -> {len(pages)} page(s)")
    return {"pages": pages}
