"""
Rate limit in-memory por IP — ventana deslizante.

Port literal del rate limit en Westfield_agent/server/index.ts.

No es persistente (vive en el proceso) ni distribuido — si el servicio escala
a múltiples réplicas el límite se vuelve por-réplica. Para el showcase está
bien; si pasa a uso real conviene mover a Redis.
"""

from __future__ import annotations

import time
from collections import defaultdict


class RateLimiter:
    def __init__(self, *, window_seconds: int = 60, max_requests: int = 12) -> None:
        self._window = window_seconds
        self._max = max_requests
        self._hits: dict[str, list[float]] = defaultdict(list)

    def hit(self, ip: str) -> bool:
        """
        Registra un hit del IP y devuelve True si superó el límite.

        Ventana deslizante: descarta hits anteriores a now - window_seconds
        antes de contar.
        """
        now = time.monotonic()
        cutoff = now - self._window
        hits = [t for t in self._hits[ip] if t >= cutoff]
        hits.append(now)
        self._hits[ip] = hits
        return len(hits) > self._max
