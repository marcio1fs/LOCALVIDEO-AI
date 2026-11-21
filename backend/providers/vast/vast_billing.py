"""Serviço de cobranças (GET /api/v0/charges/) e diagnóstico de conta.

Endpoint oficial:
- GET /api/v0/charges/
  select_filters OBRIGATÓRIO com `day` (unix seconds UTC) e opcional `type`
  (in: instance | volume | serverless); paginação com after_token (limite
  máximo de 500 por página). Retorna resultados com `amount` por contrato.

Não confundir estimativa com cobrança efetiva (§8): o Cost Manager usa
`charges` como VALOR REAL cobrado e estimativas apenas como projeções.

Shape de resposta de /users/current é tratado defensivamente (campo de saldo
não documentado detalhadamente; validado em teste real controlado na Fase 6).
"""

from __future__ import annotations

import logging
from typing import Any

from .vast_client import VastHttpClient
from .vast_schemas import ChargeRow, ChargesPage, MonthlyUsageSummary

logger = logging.getLogger("localvideo.vast.billing")

CHARGES_PATH = "/api/v0/charges"
USER_PATH = "/api/v0/users/current"


class VastBillingService:
    def __init__(self, http: VastHttpClient) -> None:
        self.http = http

    async def list_charges(
        self,
        *,
        day_start_unix: int,
        day_end_unix: int,
        contract_types: list[str] | None = None,
        limit: int = 500,
        max_pages: int = 10,
    ) -> list[ChargeRow]:
        """Cobranças no intervalo [day_start, day_end] (unix seconds UTC)."""
        filters: dict[str, Any] = {"day": {"gte": day_start_unix, "lte": day_end_unix}}
        if contract_types:
            filters["type"] = {"in": contract_types}
        rows: list[ChargeRow] = []
        next_token: str | None = None
        for _ in range(max_pages):
            query: dict[str, Any] = {
                "select_filters": filters,
                "format": "table",
                "latest_first": "true",
                "limit": min(limit, 500),
            }
            if next_token:
                query["after_token"] = next_token
            _, data = await self.http.request("GET", CHARGES_PATH, query=query)
            page = ChargesPage.model_validate(data)
            rows.extend(page.results)
            next_token = page.next_token
            if not next_token:
                break
        return rows

    async def monthly_usage(
        self,
        *,
        period_start_unix: int,
        period_end_unix: int,
    ) -> MonthlyUsageSummary:
        """Agrega cobranças reais do período por tipo de contrato."""
        rows = await self.list_charges(
            day_start_unix=period_start_unix,
            day_end_unix=period_end_unix,
        )
        summary = MonthlyUsageSummary(
            period_start_unix=period_start_unix,
            period_end_unix=period_end_unix,
            entries=rows,
        )
        for row in rows:
            amount = row.amount or 0.0
            summary.total_usd += amount
            if row.type == "instance":
                summary.instance_charges_usd += amount
            elif row.type == "volume":
                summary.volume_charges_usd += amount
            else:
                summary.other_charges_usd += amount
        return summary

    async def get_account_raw(self) -> dict[str, Any]:
        """Dados da conta (GET /api/v0/users/current) — uso diagnóstico.

        O campo de saldo não está detalhadamente documentado; retornamos o
        JSON bruto para validação em teste real controlado (Fase 6).
        """
        _, data = await self.http.request("GET", USER_PATH)
        return data
