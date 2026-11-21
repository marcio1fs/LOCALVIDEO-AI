"""Rate limiting simples (janela deslizante em memória, §10 do adendo).

- Identidade: hash da chave de API quando presente; senão IP do cliente.
- Limite: `rate_limit_requests_per_minute` + burst adicional.
- Rotas de saúde ficam isentas (monitoramento).
- Em produção multi-instância, substituir por Redis (Fase 6).
"""

from __future__ import annotations

import hashlib
import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from typing import Any

from starlette.responses import JSONResponse

RateLimitApp = Any


class SlidingWindowLimiter:
    def __init__(self, requests_per_minute: int, burst: int = 0) -> None:
        self.limit = requests_per_minute
        self.burst = burst
        self._events: dict[str, deque[float]] = defaultdict(deque)

    def _identity(self, scope: str, key: str) -> str:
        digest = hashlib.sha256(f"{scope}:{key}".encode()).hexdigest()[:24]
        return digest

    def check(self, scope: str, key: str) -> tuple[bool, int, float]:
        """(permitido, restantes, segundos até destravar)."""
        now = time.monotonic()
        window = 60.0
        identity = self._identity(scope, key)
        events = self._events[identity]
        while events and now - events[0] > window:
            events.popleft()
        effective_limit = self.limit + self.burst
        if len(events) >= effective_limit:
            retry_after = max(window - (now - events[0]), 0.1)
            return False, 0, retry_after
        events.append(now)
        return True, effective_limit - len(events), 0.0


def install_rate_limit(app: RateLimitApp, requests_per_minute: int, burst: int) -> None:
    limiter = SlidingWindowLimiter(requests_per_minute, burst)
    exempt_paths = {"/api/v1/health", "/health", "/api/v1/meta/version"}

    async def rate_limit_middleware(
        request, call_next: Callable[[Any], Awaitable[Any]]
    ) -> Any:
        if request.url.path in exempt_paths:
            return await call_next(request)

        api_key = request.headers.get("x-api-key") or request.headers.get(
            "authorization", ""
        )
        if api_key:
            scope, key = "key", api_key
        else:
            client = request.client.host if request.client else "unknown"
            scope, key = "ip", client

        allowed, remaining, retry_after = limiter.check(scope, key)
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={"detail": "Muitas requisições. Tente novamente em instantes."},
                headers={"Retry-After": str(int(retry_after) + 1)},
            )
        response = await call_next(request)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response

    app.middleware("http")(rate_limit_middleware)
