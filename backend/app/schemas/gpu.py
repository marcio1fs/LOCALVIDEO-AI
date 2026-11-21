"""Modelos de requisição/resposta das rotas de GPU e armazenamento."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from providers.vast.vast_schemas import HardwareRequirements


class GpuStatusResponse(BaseModel):
    state: str = Field(description="Estado da máquina de estados do GPU Manager.")
    provider: str = "vast.ai"
    provider_configured: bool
    mutations_enabled: bool = Field(
        description="Se as operações que geram cobrança estão habilitadas no servidor."
    )
    message: str
    instance_id: int | None = None
    gpu: dict[str, Any] | None = None
    volume_id: int | None = None
    session: dict[str, Any]
    budget: dict[str, Any]
    queue_size: int
    max_concurrent_jobs: int
    idle_timeout_minutes: int


class GpuStartRequest(BaseModel):
    requirements: HardwareRequirements | None = Field(
        default=None,
        description="Requisitos de hardware editáveis; ausente = perfil padrão do servidor.",
    )
    volume_id: int | None = Field(
        default=None,
        description="Volume persistente a montar em /data. Ausente = primeiro volume disponível.",
    )
    estimated_hours: float | None = Field(
        default=None, gt=0, le=24, description="Horas estimadas da sessão (para orçamento)."
    )
    confirm_cost: bool = Field(
        default=True,
        description="Confirmação explícita de custo (obrigatória para iniciar).",
    )


class GpuStartResponse(BaseModel):
    state: str
    message: str
    instance_id: int | None = None
    errors: list[str] = Field(default_factory=list)
    gpu: dict[str, Any] | None = None


class GpuStopRequest(BaseModel):
    mode: str = Field(
        default="stop",
        description="'stop' mantém a instância (sem custo de GPU); 'destroy' exige confirmação de persistência.",
    )
    data_persisted_confirmed: bool = Field(
        default=False,
        description="Confirmação de que os dados importantes estão no volume persistente.",
    )


class GpuOffersQuery(BaseModel):
    requirements: HardwareRequirements | None = None
    estimated_hours: float | None = Field(default=None, gt=0, le=24)


class GpuCostEstimateResponse(BaseModel):
    feasible: bool
    offer: dict[str, Any] | None = None
    cost_estimate: dict[str, Any] | None = None
    volume: dict[str, Any] | None = None
    considered: int = 0
    rejection_summary: dict[str, int] = Field(default_factory=dict)
    message: str | None = None


class GpuUsageResponse(BaseModel):
    budget: dict[str, Any]
    ledger: list[dict[str, Any]]
    history: list[dict[str, Any]]
    note: str = Field(
        default=(
            "Cobranças reais são consolidadas a partir de GET /api/v0/charges/ da Vast.ai; "
            "estimativas e reservas vêm do Cost Manager."
        ),
        description="Nota metodológica sobre origem dos valores.",
    )


class StorageStatusResponse(BaseModel):
    volumes: list[dict[str, Any]]
    mount_path: str
    note: str


class BudgetUpdateRequest(BaseModel):
    monthly_budget_brl: float | None = Field(
        default=None,
        gt=0,
        le=100_000,
        description="Novo limite mensal em reais. Omitido = sem alteração.",
    )
    usd_to_brl_rate: float | None = Field(
        default=None,
        gt=0.01,
        le=100,
        description="Nova taxa USD→BRL para estimativas. Omitido = sem alteração.",
    )


class BudgetResponse(BaseModel):
    budget: dict[str, Any]
    message: str = "Orçamento atualizado e persistido."


class ErrorResponse(BaseModel):
    error: dict[str, Any] = Field(
        description='{"code": str, "message": str, ...}'
    )
