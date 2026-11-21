"""Serviço de busca de ofertas (POST /api/v0/bundles/).

Corpo validado na documentação oficial e no SDK:
- filtros como objetos {op: valor} (eq, neq, gt, lt, gte, lte, in, notin);
- ``verified``/``rentable``/``rented``/``external`` default (mesmo do CLI);
- ``order`` como pares [campo, direção];
- ``type``: on-demand | bid | reserved (``interruptible`` do CLI -> ``bid``);
- ``allocated_storage`` para precificação do disco;
- ``gpu_ram`` em MB (quirk oficial da API REST).
"""

from __future__ import annotations

import logging
from typing import Any

from .vast_client import VastHttpClient
from .vast_exceptions import VastError
from .vast_schemas import HardwareRequirements, RentalType, VastOffer

logger = logging.getLogger("localvideo.vast.offers")

SEARCH_PATH = "/api/v0/bundles/"


class VastOffersService:
    """Consulta de ofertas com filtros de hardware estruturados."""

    def __init__(self, http: VastHttpClient) -> None:
        self.http = http

    async def search(
        self,
        requirements: HardwareRequirements,
        rental_type: RentalType = RentalType.ON_DEMAND,
        allocated_storage_gb: float = 20.0,
    ) -> list[VastOffer]:
        """Busca ofertas que atendem aos requisitos; sem filtros de score aqui.

        A filtragem semântica (score, motivo de rejeição) fica no
        ``app.services.offer_selector``; aqui apenas convertemos requisitos em
        filtros aceitos pela API.
        """
        body = self._build_body(requirements, rental_type, allocated_storage_gb)
        _, data = await self.http.request("POST", SEARCH_PATH, json_body=body)
        raw_offers = data.get("offers")
        if not isinstance(raw_offers, list):
            raise VastError(
                "Resposta inesperada da busca de ofertas (campo 'offers' ausente).",
                code="vast_unexpected_response",
                detail=data,
            )
        offers = [VastOffer.model_validate(item) for item in raw_offers]
        logger.info("Vast.ai: %d ofertas retornadas (limite %d)", len(offers), body.get("limit", 0))
        return offers

    async def search_raw(
        self,
        query: dict[str, Any] | None = None,
        rental_type: RentalType = RentalType.ON_DEMAND,
        order: list[list[str]] | None = None,
        limit: int | None = None,
        allocated_storage_gb: float = 20.0,
    ) -> list[dict[str, Any]]:
        """Busca com query dict bruta (para diagnóstico/administração)."""
        body: dict[str, Any] = {
            "verified": {"eq": True},
            "external": {"eq": False},
            "rentable": {"eq": True},
            "rented": {"eq": False},
        }
        if query:
            body.update(query)
        body["order"] = order or [["dph_total", "asc"]]
        body["type"] = rental_type.value
        if limit:
            body["limit"] = int(limit)
        body["allocated_storage"] = allocated_storage_gb
        _, data = await self.http.request("POST", SEARCH_PATH, json_body=body)
        offers = data.get("offers") or []
        return offers if isinstance(offers, list) else []

    # ------------------------------------------------------------------
    @staticmethod
    def _build_body(
        requirements: HardwareRequirements,
        rental_type: RentalType,
        allocated_storage_gb: float,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "verified": {"eq": requirements.require_verified},
            "external": {"eq": False},
            "rentable": {"eq": requirements.require_rentable},
            "rented": {"eq": False},
            "order": [["dph_total", "asc"]],
            "type": rental_type.value,
            "limit": requirements.max_results,
            "allocated_storage": allocated_storage_gb,
        }

        if requirements.allowed_gpus:
            body["gpu_name"] = {"in": list(requirements.allowed_gpus)}
        if requirements.min_vram_mb:
            body["gpu_ram"] = {"gte": requirements.min_vram_mb}
        if requirements.min_gpu_count:
            body["num_gpus"] = {"gte": requirements.min_gpu_count}
        if requirements.min_cpu_ram_mb:
            body["cpu_ram"] = {"gte": requirements.min_cpu_ram_mb}
        if requirements.min_cpu_cores:
            body["cpu_cores"] = {"gte": requirements.min_cpu_cores}
        if requirements.min_disk_gb:
            body["disk_space"] = {"gte": requirements.min_disk_gb}
        if requirements.min_reliability:
            body["reliability"] = {"gte": requirements.min_reliability}
        if requirements.min_cuda_version:
            body["cuda_max_good"] = {"gte": requirements.min_cuda_version}
        if requirements.volume_machine_id is not None:
            body["machine_id"] = {"eq": requirements.volume_machine_id}
        if requirements.max_dph_total is not None:
            body["dph_total"] = {"lte": requirements.max_dph_total}

        return body
