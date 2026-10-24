"""In-memory sliding-window rate limits for sign-in and sign-up endpoints.

Per process: fine for a single container. Multi-replica deployments should put limits in front
(e.g. the reverse proxy) or swap this for a shared store.
"""
import time
from collections import defaultdict, deque

from fastapi import HTTPException

_hits: dict[str, deque[float]] = defaultdict(deque)


def limit(key: str, max_hits: int, per_seconds: int) -> None:
    now = time.monotonic()
    q = _hits[key]
    while q and now - q[0] > per_seconds:
        q.popleft()
    if len(q) >= max_hits:
        raise HTTPException(429, "Too many attempts. Please wait a few minutes and try again.")
    q.append(now)


def reset_for_tests() -> None:
    _hits.clear()
