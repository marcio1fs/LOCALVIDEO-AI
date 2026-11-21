"""Cliente HTTP assíncrono para a API REST oficial da Vast.ai.

Comportamento espelha o SDK/CLI oficial (vast-ai/vast-cli, vastai/api/client.py):

- Base URL: https://console.vast.ai ; paths sem prefixo recebem ``/api/v0``.
- Autenticação: header ``Authorization: Bearer <API_KEY>``.
- Retries: 429 (exceto quota diária de busca), 502, 503, 504 e falhas de
  transporte (conexão/timeout), com backoff exponencial e ``Retry-After``.
- Erros 4xx restantes NÃO são retentáveis (ex.: oferta indisponível).

Além do comportamento oficial, o Control Plane adiciona:
- camada de idempotência local para operações de mutação (PUT/POST/DELETE):
  mesma operação (método+path+hash do corpo) dentro da janela de TTL não é
  reenviada — protege contra duplicação em retry (§3, §9);
- redação da credencial em qualquer erro/log;
- transporte injetável (httpx.AsyncClient) para testes com respx/mocks.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from .vast_exceptions import (
    VastAuthError,
    VastError,
    VastRateLimitError,
    VastTransportError,
    map_response_error,
)

logger = logging.getLogger("localvideo.vast")

# Códigos retentáveis — iguais aos do SDK oficial (_RETRYABLE_STATUS).
RETRYABLE_STATUS = {429, 502, 503, 504}


@dataclass
class VastClientConfig:
    api_key: str | None = None
    server_url: str = "https://console.vast.ai"
    retry_attempts: int = 3
    backoff_base_seconds: float = 0.15
    backoff_factor: float = 1.5
    max_retry_after_seconds: float = 60.0
    timeout_seconds: float = 120.0
    idempotency_ttl_seconds: int = 300
    user_agent: str = "localvideo-ai-control-plane/0.1"


@dataclass
class _IdempotentRecord:
    response_json: dict[str, Any]
    status_code: int
    created_at: float
    fingerprint: str = field(default="")


def _fingerprint(method: str, path: str, body: Any) -> str:
    canonical = json.dumps(body, sort_keys=True, ensure_ascii=False, default=str)
    digest = hashlib.sha256(f"{method}:{path}:{canonical}".encode()).hexdigest()
    return digest


class VastHttpClient:
    """Cliente HTTP com retry, idempotência e mapeamento de erros."""

    def __init__(
        self,
        config: VastClientConfig,
        http: httpx.AsyncClient | None = None,
        clock: Any = None,
        sleep: Any = None,
    ) -> None:
        self.config = config
        self._http = http or httpx.AsyncClient(
            base_url=config.server_url,
            timeout=config.timeout_seconds,
            headers={
                "User-Agent": config.user_agent,
                "Accept": "application/json",
            },
        )
        self._owns_http = http is None
        self._clock = clock or time.monotonic
        self._sleep = sleep or asyncio.sleep
        self._idempotency_store: dict[str, _IdempotentRecord] = {}

    # ------------------------------------------------------------------
    # Ciclo de vida
    # ------------------------------------------------------------------
    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    # ------------------------------------------------------------------
    # Requisição principal
    # ------------------------------------------------------------------
    async def request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, Any] | None = None,
        json_body: Any = None,
        idempotency: bool = False,
    ) -> tuple[int, dict[str, Any]]:
        """Executa uma chamada REST e devolve (status, json).

        Levanta VastError tipado em qualquer falha mapeada.
        """
        full_path = path if path.startswith("/api/v") else f"/api/v0{path}"
        if not full_path.endswith("/"):
            full_path += "/"
        key = None
        if idempotency and method in ("PUT", "POST", "DELETE") and json_body is not None:
            key = _fingerprint(method, full_path, json_body)
            cached = self._replay_if_cached(key)
            if cached is not None:
                logger.info("Vast.ai: replay idempotente de %s %s", method, full_path)
                return cached.status_code, cached.response_json

        headers = self._auth_headers()
        backoff = self.config.backoff_base_seconds
        last_error: VastError | None = None

        for attempt in range(1, self.config.retry_attempts + 1):
            try:
                response = await self._http.request(
                    method,
                    full_path,
                    params=self._encode_query(query),
                    json=json_body,
                    headers=headers,
                )
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                last_error = VastTransportError(
                    f"Falha de rede ao contatar a Vast.ai: {type(exc).__name__}",
                    code="vast_transport_error",
                )
                if attempt < self.config.retry_attempts:
                    await self._sleep(backoff)
                    backoff *= self.config.backoff_factor
                    continue
                raise last_error from exc

            status = response.status_code

            if status < 400:
                self._store_idempotent(key, status, response)
                return status, self._parse_json(response)

            payload = self._safe_json(response)

            if status in RETRYABLE_STATUS and status != 429 and attempt < self.config.retry_attempts:
                await self._sleep(backoff)
                backoff *= self.config.backoff_factor
                continue

            if status == 429:
                error = map_response_error(status, payload, dict(response.headers))
                assert isinstance(error, VastRateLimitError)
                if not error.quota_exceeded and attempt < self.config.retry_attempts:
                    wait = error.retry_after_seconds
                    if wait is None or wait > self.config.max_retry_after_seconds:
                        wait = min(backoff, self.config.max_retry_after_seconds)
                    await self._sleep(wait)
                    backoff *= self.config.backoff_factor
                    continue
                raise error

            raise map_response_error(status, payload, dict(response.headers))

        raise last_error or VastError("Falha desconhecida na chamada Vast.ai")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _auth_headers(self) -> dict[str, str]:
        if not self.config.api_key:
            raise VastAuthError(
                "VAST_API_KEY não configurada no servidor de controle.",
                code="vast_key_missing",
            )
        return {"Authorization": f"Bearer {self.config.api_key}"}

    @staticmethod
    def _encode_query(query: dict[str, Any] | None) -> dict[str, str] | None:
        if not query:
            return None
        encoded: dict[str, str] = {}
        for key, value in query.items():
            if isinstance(value, str):
                encoded[key] = value
            else:
                encoded[key] = json.dumps(value, ensure_ascii=False)
        return encoded

    @staticmethod
    def _parse_json(response: httpx.Response) -> dict[str, Any]:
        try:
            data = response.json()
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {"_raw": data}

    @staticmethod
    def _safe_json(response: httpx.Response) -> Any:
        try:
            return response.json()
        except ValueError:
            return response.text[:500]

    # ------------------------------------------------------------------
    # Idempotência local (mutações)
    # ------------------------------------------------------------------
    def _store_idempotent(self, key: str | None, status: int, response: httpx.Response) -> None:
        if key is None or status >= 400:
            return
        self._idempotency_store[key] = _IdempotentRecord(
            response_json=self._parse_json(response),
            status_code=status,
            created_at=self._clock(),
            fingerprint=key,
        )
        self._prune_store()

    def _replay_if_cached(self, key: str) -> _IdempotentRecord | None:
        record = self._idempotency_store.get(key)
        if record is None:
            return None
        ttl = self.config.idempotency_ttl_seconds
        if self._clock() - record.created_at > ttl:
            self._idempotency_store.pop(key, None)
            return None
        return record

    def _prune_store(self) -> None:
        now = self._clock()
        expired = [
            key
            for key, record in self._idempotency_store.items()
            if now - record.created_at > self.config.idempotency_ttl_seconds
        ]
        for key in expired:
            self._idempotency_store.pop(key, None)

    def clear_idempotency(self) -> None:
        self._idempotency_store.clear()

    # ------------------------------------------------------------------
    # Retry manual exposto (usado por serviços que precisam de jitter)
    # ------------------------------------------------------------------
    @staticmethod
    def jitter(base: float) -> float:
        """Pequeno jitter (±10%) para evitar sincronização de retries."""
        return base * (0.9 + 0.2 * random.random())
