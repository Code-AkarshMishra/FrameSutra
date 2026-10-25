"""Process-local counters and structured logging helpers."""
from __future__ import annotations

import threading
from collections import Counter

_lock = threading.Lock()
_counters: Counter[str] = Counter()


def increment(name: str, amount: int = 1) -> None:
    with _lock:
        _counters[name] += amount


def snapshot() -> dict[str, int]:
    with _lock:
        return dict(_counters)
