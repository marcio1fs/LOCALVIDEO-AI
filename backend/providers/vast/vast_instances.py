"""Serviço de instâncias (create / show / manage / destroy).

Endpoints oficiais usados:
- Criação:   PUT  /api/v0/asks/{offer_id}/  -> {"success": true, "new_contract": <id>}
- Consulta:  GET  /api/v0/instances/{id}/  (query owner=me)
- Listagem:  GET  /api/v1/instances/       (paginada, máx. 25/página, next_token)
- Estado:    PUT  /api/v0/instances/{id}/  ({"state": "running"|"stopped"})
- Destruição: DELETE /api/v0/instances/{id}/ (irreversível)

Regras do adendo implementadas aqui:
- Toda mutação passa por `mutation_gate` (portão de cobrança explícito);
- create usa idempotência local (retry não duplica contrato);
- wait_for_running detecta o "poll trap" oficial (exited/unknown/offline)
  e NUNCA destrói a instância automaticamente;
- destroy exige confirmação explícita de persistência de dados.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from .vast_client import VastHttpClient
from .vast_exceptions import (
    VastError,
    VastInstanceCreateError,
    VastInstanceNotFoundError,
    VastInstanceUnrecoverableError,
    VastRateLimitError,
)
from .vast_schemas import CreateInstanceRequest, VastInstance

logger = logging.getLogger("localvideo.vast.instances")

CREATE_PATH = "/api/v0/asks/{offer_id}/"
INSTANCE_PATH = "/api/v0/instances/{id}/"
INSTANCE_LIST_V1_PATH = "/api/v1/instances/"

# Estados terminais do poll-trap (Key Quirks do OpenAPI oficial).
POLL_TRAP_STATUSES = {"exited", "unknown", "offline"}


class MutationGate:
    """Portão de cobrança: exige habilitação explícita (§14 do adendo).

    Em desenvolvimento local, nenhuma instância é criada. Para permitir
    operações reais: LV_VAST_ENABLE_MUTATIONS=true + VAST_API_KEY válida.
    """

    def __init__(self, enabled: bool, reason: str | None = None) -> None:
        self.enabled = enabled
        self.reason = reason or (
            "Operações que geram cobrança estão desabilitadas "
            "(LV_VAST_ENABLE_MUTATIONS=false). Habilite explicitamente para "
            "criar/alterar instâncias reais na Vast.ai."
        )

    def require(self) -> None:
        if not self.enabled:
            raise VastError(self.reason, code="vast_mutations_disabled")


class VastInstancesService:
    def __init__(
        self,
        http: VastHttpClient,
        mutation_gate: MutationGate,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self.http = http
        self.gate = mutation_gate
        self._sleep = sleep or asyncio.sleep

    # ------------------------------------------------------------------
    # Leitura (sem portão)
    # ------------------------------------------------------------------
    async def get(self, instance_id: int) -> VastInstance:
        _, data = await self.http.request(
            "GET", INSTANCE_PATH.format(id=instance_id), query={"owner": "me"}
        )
        if not data.get("success", True) and data.get("error"):
            raise VastInstanceNotFoundError(str(data.get("msg")), code=data.get("error"))
        return VastInstance.model_validate(data)

    async def list(
        self,
        *,
        status: str | None = None,
        max_pages: int = 8,
        page_size: int = 25,
    ) -> list[VastInstance]:
        """Lista paginada (API v1, keyset pagination com next_token)."""
        instances: list[VastInstance] = []
        next_token: str | None = None
        for _ in range(max_pages):
            query: dict[str, Any] = {"limit": min(page_size, 25)}
            if status:
                query["select_filters"] = {"actual_status": {"eq": status}}
            if next_token:
                query["after_token"] = next_token
            _, data = await self.http.request("GET", INSTANCE_LIST_V1_PATH, query=query)
            for item in data.get("instances") or []:
                instances.append(VastInstance.model_validate(item))
            next_token = data.get("next_token")
            if not next_token:
                break
        return instances

    # ------------------------------------------------------------------
    # Mutações (com portão de cobrança)
    # ------------------------------------------------------------------
    async def create(self, request: CreateInstanceRequest) -> int:
        """Cria instância a partir de uma oferta. Retorna o ID do contrato."""
        self.gate.require()
        payload = self._build_create_payload(request)
        _, data = await self.http.request(
            "PUT",
            CREATE_PATH.format(offer_id=request.offer_id),
            json_body=payload,
            idempotency=True,
        )
        contract_id = data.get("new_contract")
        if data.get("success") is not True or contract_id is None:
            raise VastInstanceCreateError(
                str(data.get("msg") or "Resposta de criação sem 'new_contract'."),
                code=data.get("error") or "vast_create_failed",
                detail=data,
            )
        logger.info("Vast.ai: instância criada (contrato %s, oferta %s)", contract_id, request.offer_id)
        return int(contract_id)

    async def set_state(self, instance_id: int, state: str) -> None:
        """start/stop via manage-instance. state ∈ {"running", "stopped"}."""
        self.gate.require()
        await self.http.request(
            "PUT",
            INSTANCE_PATH.format(id=instance_id),
            json_body={"state": state},
            idempotency=True,
        )

    async def destroy(self, instance_id: int, *, data_persisted_confirmed: bool) -> None:
        """Destrói a instância — IRREVERSÍVEL.

        Exige confirmação explícita de que os dados importantes estão no
        volume persistente (§5/§7 do adendo). O adaptador nunca apaga volumes.
        """
        self.gate.require()
        if not data_persisted_confirmed:
            raise VastError(
                "Destruição bloqueada: confirmar persistência dos dados "
                "(data_persisted_confirmed=True) antes de destruir a instância.",
                code="vast_destroy_blocked",
            )
        await self.http.request(
            "DELETE",
            INSTANCE_PATH.format(id=instance_id),
            json_body={},
            idempotency=True,
        )
        logger.info("Vast.ai: instância %s destruída", instance_id)

    # ------------------------------------------------------------------
    # Polling de prontidão
    # ------------------------------------------------------------------
    async def wait_for_running(
        self,
        instance_id: int,
        *,
        timeout_seconds: float = 900.0,
        poll_interval_seconds: float = 5.0,
        on_poll: Callable[[VastInstance], None] | None = None,
    ) -> VastInstance:
        """Aguarda actual_status == running.

        Poll-trap oficial: exited/unknown/offline nunca chegam a running —
        levanta VastInstanceUnrecoverableError imediatamente. A decisão de
        destruir/recriar é do GPU Manager, com confirmação.
        """
        elapsed = 0.0
        while True:
            instance = await self.get(instance_id)
            if on_poll is not None:
                on_poll(instance)
            status = instance.actual_status
            if status == "running":
                return instance
            if status in POLL_TRAP_STATUSES:
                raise VastInstanceUnrecoverableError(
                    f"Instância {instance_id} em '{status}' e não chegará a 'running' "
                    "(poll-trap documentado pela Vast.ai). Revisar e recriar manualmente.",
                    status=None,
                    code="vast_instance_poll_trap",
                    detail={"actual_status": status, "instance_id": instance_id},
                )
            if elapsed >= timeout_seconds:
                raise VastError(
                    f"Instância {instance_id} não ficou 'running' em {timeout_seconds}s "
                    f"(último estado: {status}).",
                    code="vast_instance_ready_timeout",
                    detail={"actual_status": status, "instance_id": instance_id},
                )
            await self._sleep(poll_interval_seconds)
            elapsed += poll_interval_seconds

    # ------------------------------------------------------------------
    @staticmethod
    def _build_create_payload(request: CreateInstanceRequest) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "client_id": "me",
            "image": request.image,
            "env": dict(request.env),
            "disk": request.disk_gb,
            "label": request.label,
            "runtype": request.runtype,
            "cancel_unavail": request.cancel_unavail,
            "force": request.force,
            "target_state": request.target_state,
        }
        if request.args:
            payload["args"] = list(request.args)
        if request.onstart:
            payload["onstart"] = request.onstart
        if request.volume is not None:
            payload["volume_info"] = request.volume.to_api()
        return payload


__all__ = [
    "MutationGate",
    "POLL_TRAP_STATUSES",
    "VastInstancesService",
    "VastRateLimitError",
]
