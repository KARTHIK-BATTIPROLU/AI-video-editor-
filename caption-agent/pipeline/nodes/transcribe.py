"""transcribe — faster-whisper with word-level timestamps -> list[Word]."""

import os

from ..state import CaptionState, Word
from ._log import log


def transcribe(state: CaptionState) -> dict:
    audio = state["audio_path"]
    language = state.get("language") or None

    # Lazy import so the graph is importable without the ML stack installed.
    from faster_whisper import WhisperModel

    model_size = os.environ.get("WHISPER_MODEL", "base")
    device = os.environ.get("WHISPER_DEVICE", "auto")
    compute_type = os.environ.get(
        "WHISPER_COMPUTE", "int8" if device != "cuda" else "float16"
    )

    log("transcribe", f"loading whisper '{model_size}' (device={device})")
    model = WhisperModel(model_size, device=device, compute_type=compute_type)

    segments, info = model.transcribe(
        audio,
        word_timestamps=True,
        language=language,
        vad_filter=True,
    )

    words: list[Word] = []
    for seg in segments:
        for w in (seg.words or []):
            text = (w.word or "").strip()
            if not text:
                continue
            words.append(Word(text=text, start=float(w.start), end=float(w.end)))

    log("transcribe", f"detected lang={getattr(info, 'language', '?')}, {len(words)} words")
    return {"words": words}
