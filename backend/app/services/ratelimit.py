"""Lightweight in-memory, per-IP rate limiting for sensitive endpoints.

A sliding window of request timestamps per (scope, client-IP). O(1) per request, a few bytes per
tracked IP — no external store, so it costs nothing extra while the API runs as a single task.
(If the API is ever scaled to multiple tasks, each keeps its own counter; back it with Redis then.)

Used as a route dependency: `dependencies=[Depends(ratelimit.limit("login"))]`.
"""
from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import Request, HTTPException, status

from app.config import settings

# scope -> (max_calls, window_seconds). Generous enough that a fumbling human never trips it,
# tight enough to stop automated guessing/flooding.
LIMITS: dict[str, tuple[int, int]] = {
    "login": (20, 60),
    "register": (15, 60),
    "claim": (15, 60),
    "forgot_password": (5, 60),
    "change_password": (10, 60),
}

_hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)


def reset() -> None:
    """Clear all counters (used by tests)."""
    _hits.clear()


def _client_ip(request: Request) -> str:
    # Behind CloudFront/ALB the real client is the leftmost X-Forwarded-For entry.
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _sweep(now: float) -> None:
    """Drop stale keys so memory stays bounded under many distinct IPs."""
    for key in list(_hits):
        dq = _hits[key]
        while dq and dq[0] < now - 3600:
            dq.popleft()
        if not dq:
            del _hits[key]


def limit(scope: str):
    max_calls, window = LIMITS[scope]

    def dependency(request: Request) -> None:
        if not settings.rate_limit_enabled:
            return
        key = (scope, _client_ip(request))
        now = time.monotonic()
        dq = _hits[key]
        cutoff = now - window
        while dq and dq[0] < cutoff:
            dq.popleft()
        if len(dq) >= max_calls:
            retry = int(dq[0] + window - now) + 1
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Too many attempts. Try again in {retry}s.",
                headers={"Retry-After": str(retry)},
            )
        dq.append(now)
        if len(_hits) > 10_000:
            _sweep(now)

    return dependency
