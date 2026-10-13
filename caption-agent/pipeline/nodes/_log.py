"""Tiny tagged logger so resumability / interrupt behavior is observable."""

import time

_T0 = time.time()


def log(tag: str, msg: str) -> None:
    print(f"[{time.time() - _T0:7.2f}s] [{tag}] {msg}", flush=True)
