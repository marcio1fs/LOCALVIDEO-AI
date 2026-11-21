"""Exceções do adaptador Vast.ai.

Mapeia respostas HTTP/erros de transporte da API REST oficial
(https://console.vast.ai) para exceções tipadas, de modo que o restante do
Control Plane nunca precise conhecer detalhes do provedor.

Fonte: documentação oficial
- https://docs.vast.ai/api-reference/rate-limits-and-errors
- Páginas de cada endpoint (create-instance, manage-instance, destroy-instance,
  search-offers, volumes, charges).
"""

from __future__ import annotations

from typing import Any

# Códigos de erro documentados nas respostas 400/403/404/410 do endpoint de
# criação de instância (create-instance.md).
OFFER_UNAVAILABLE_ERRORS = {"no_such_ask", "invalid_args"}


class VastError(Exception):
    """Erro base do adaptador Vast.ai."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        code: str | None = None,
        detail: Any = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code or "vast_error"
        self.detail = detail

    def __str__(self) -> str:  # pragma: no cover - legibilidade
        if self.status is not None:
            return f"[{self.status}] {self.code}: {self.message}"
        return f"{self.code}: {self.message}"


class VastAuthError(VastError):
    """Credenciais inválidas/ausentes (401/403 na API da Vast.ai).

    A documentação registra que falha de chave pode vir como 404
    ("Invalid user key") no endpoint de busca de ofertas — ver
    search-offers.md, response '404: Unauthorized - invalid or missing API key'.
    """

    def __init__(
        self,
        message: str = "Credenciais Vast.ai inválidas ou ausentes.",
        *,
        code: str = "vast_auth_error",
        **kwargs: Any,
    ) -> None:
        super().__init__(message, code=code, **kwargs)


class VastRateLimitError(VastError):
    """429 — limite de requisições atingido.

    Responses: {"detail": "API requests too frequent endpoint threshold=X"}.
    `retry_after_seconds` é lido do header Retry-After quando presente.
    """

    def __init__(
        self,
        message: str = "Limite de requisições da Vast.ai atingido.",
        *,
        retry_after_seconds: float | None = None,
        quota_exceeded: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(message, code="vast_rate_limit_error", **kwargs)
        self.retry_after_seconds = retry_after_seconds
        # Quota DIÁRIA de busca: o SDK oficial não faz retry (reseta só à
        # meia-noite UTC) — ver is_search_quota_exceeded() no client oficial.
        self.quota_exceeded = quota_exceeded
        self.retryable = not quota_exceeded


class VastServerError(VastError):
    """5xx — erro do lado do provedor (502/503/504 são retentáveis)."""


class VastTransportError(VastError):
    """Falha de rede/timeout ao falar com a Vast.ai (retentável)."""


class VastSearchQuotaError(VastRateLimitError):
    """429 com error == search_quota_exceeded — NÃO retentável no dia."""


class VastOfferUnavailableError(VastError):
    """A oferta (ask) não existe mais / não está disponível (400/404/410).

    Documentado em create-instance.md:
    - 400/404 invalid_args: "no_such_ask Instance type by id X is not available"
    - 410 no_such_ask: "Instance type X is no longer available"
    """


class VastInstanceCreateError(VastError):
    """Falha genérica na criação de instância."""


class VastInstanceNotFoundError(VastError):
    """Instância não encontrada (404 em show/manage/destroy)."""


class VastInstanceUnrecoverableError(VastError):
    """Poll-trap documentado: actual_status em {exited, unknown, offline}.

    "If actual_status becomes exited, unknown, or offline it will never reach
    running — destroy and retry" (Key Quirks do OpenAPI oficial).
    O adaptador NUNCA destrói automaticamente; apenas sinaliza.
    """

    ACTUAL_STATUSES = ("exited", "unknown", "offline")


class VastVolumeError(VastError):
    """Erro em operações de volume."""


class VastVolumeHostMismatchError(VastVolumeError):
    """Volume local pertence a outro host físico que a oferta selecionada.

    Documentação oficial (guides/instances/storage/volumes):
    "A volume is physically tied to the machine it was created on. It can only
    be attached to instances running on the same physical machine."
    """


def map_response_error(status: int, payload: Any, headers: dict[str, str] | None = None) -> VastError:
    """Converte (status, corpo) da Vast.ai na exceção tipada apropriada.

    `payload` pode ser dict (JSON) ou string. Erros conhecidos:
      - {"success": false, "error": "...", "msg": "..."}
      - {"detail": "API requests too frequent endpoint threshold=4.5"}
      - 404 {"error": ..., "msg": "Invalid user key"} (busca de ofertas)
    """
    headers = headers or {}
    payload_dict: dict[str, Any] = {}
    if isinstance(payload, dict):
        payload_dict = payload
    payload_text = str(payload)

    if status in (401, 403):
        return VastAuthError(
            payload_dict.get("msg") or payload_dict.get("detail") or payload_text,
            status=status,
            code=payload_dict.get("error"),
        )

    # A busca de ofertas responde 404 com "Invalid user key" quando a chave é
    # inválida (search-offers.md, response 404 "Unauthorized").
    if status == 404 and "invalid user key" in payload_text.lower():
        return VastAuthError(payload_dict.get("msg", payload_text), status=status)

    if status == 429:
        detail = payload_dict.get("detail") or payload_dict.get("msg") or payload_text
        retry_after = None
        raw_retry_after = headers.get("retry-after")
        if raw_retry_after is not None:
            try:
                retry_after = float(raw_retry_after)
            except (TypeError, ValueError):
                retry_after = None
        quota = payload_dict.get("error") == "search_quota_exceeded"
        if quota:
            return VastSearchQuotaError(str(detail), status=429, quota_exceeded=True)
        return VastRateLimitError(str(detail), status=429, retry_after_seconds=retry_after)

    if 500 <= status <= 599:
        return VastServerError(payload_text, status=status, code=payload_dict.get("error"))

    if status == 404:
        return VastInstanceNotFoundError(
            payload_dict.get("msg") or payload_text, status=status, code=payload_dict.get("error")
        )

    error_code = payload_dict.get("error")
    msg = payload_dict.get("msg") or payload_dict.get("detail") or payload_text
    if error_code in OFFER_UNAVAILABLE_ERRORS and ("no_such_ask" in msg or "not available" in msg.lower()):
        return VastOfferUnavailableError(msg, status=status, code=error_code)

    return VastError(msg, status=status, code=error_code)
