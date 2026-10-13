"""Coerce checkpoint-deserialized values back into their dataclasses.

LangGraph's serializer usually restores dataclasses intact, but a plain dict can
slip through (e.g. hand-built state). These helpers make downstream nodes robust
either way.
"""

from ..state import Word, SafeZone, Page


def as_word(w) -> Word:
    if isinstance(w, Word):
        return w
    return Word(text=w["text"], start=float(w["start"]), end=float(w["end"]))


def as_safezone(z) -> SafeZone:
    if isinstance(z, SafeZone):
        return z
    return SafeZone(
        start=float(z["start"]), end=float(z["end"]),
        x=float(z["x"]), y=float(z["y"]), anchor=z["anchor"],
    )


def as_page(p) -> Page:
    if isinstance(p, Page):
        return Page(p.start_ms, p.end_ms, p.x, p.y, p.anchor,
                    [as_word(w) for w in p.words])
    return Page(
        start_ms=int(p["start_ms"]), end_ms=int(p["end_ms"]),
        x=float(p["x"]), y=float(p["y"]), anchor=p["anchor"],
        words=[as_word(w) for w in p["words"]],
    )
