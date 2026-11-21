"""Schemas Pydantic do adaptador Vast.ai.

Todos os modelos de resposta usam ``extra="allow"``: a API retorna dezenas de
campos e evolve sem aviso; registramos explicitamente apenas os campos que o
Control Plane consome. Nomes de campos refletem EXATAMENTE os retornados pela
API oficial (ex.: ``gpu_ram`` em MB, ``dph_total`` em USD/hora).

Fontes dos campos (documentação oficial, seção OpenAPI de cada endpoint):
- search offers  -> https://docs.vast.ai/api-reference/search/search-offers.md
- show instances -> https://docs.vast.ai/api-reference/instances/show-instances.md
- list volumes   -> https://docs.vast.ai/api-reference/volumes/list-volumes.md
- show charges   -> https://docs.vast.ai/api-reference/billing/show-charges.md
- create/manage/destroy instance -> .../instances/*.md
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class RentalType(StrEnum):
    """Tipo de contrato de busca (body `type` em POST /api/v0/bundles/)."""

    ON_DEMAND = "on-demand"
    RESERVED = "reserved"
    BID = "bid"  # interruptible (spot)


# ---------------------------------------------------------------------------
# Filtros de busca (operadores oficiais: eq, neq, gt, lt, gte, lte, in, notin)
# ---------------------------------------------------------------------------


class FilterOp(BaseModel):
    """Operador estruturado usado no corpo de POST /api/v0/bundles/."""

    eq: Any | None = None
    neq: Any | None = None
    gt: Any | None = None
    lt: Any | None = None
    gte: Any | None = None
    lte: Any | None = None
    in_: list[Any] | None = Field(default=None, alias="in")
    notin: list[Any] | None = None

    model_config = ConfigDict(populate_by_name=True)

    def to_api(self) -> dict[str, Any]:
        data = self.model_dump(exclude_none=True, by_alias=True)
        return {k: v for k, v in data.items() if v is not None}


class HardwareRequirements(BaseModel):
    """Requisitos de hardware editáveis (§4 do adendo).

    Não fixa RTX 4090: `allowed_gpus` é uma lista configurável e todos os
    limiares são parâmetros. Valores padrão derivam da configuração
    preferencial inicial do adendo (24 GB VRAM, 32 GB RAM, SSD, CUDA 11.8+).
    """

    allowed_gpus: list[str] | None = Field(
        default=None, description="Nomes aceitos (gpu_name). None = qualquer GPU."
    )
    min_vram_mb: int = 24576
    min_gpu_count: int = 1
    min_cpu_ram_mb: int = 32768
    min_cpu_cores: int = 4
    min_disk_gb: float = 60.0
    min_reliability: float = 0.98
    min_compute_cap: float | None = 8.0
    min_cuda_version: float | None = 11.8
    max_dph_total: float | None = None
    require_rentable: bool = True
    require_verified: bool = True
    exclude_vms: bool = True
    volume_machine_id: int | None = Field(
        default=None,
        description=(
            "Se definido, aceita apenas ofertas no MESMO host físico do volume "
            "(volumes locais da Vast.ai são vinculados à máquina)."
        ),
    )
    max_results: int = 25


# ---------------------------------------------------------------------------
# Oferta (POST /api/v0/bundles/ -> offers[])
# ---------------------------------------------------------------------------


class VastOffer(BaseModel):
    """Subconjunto dos campos da oferta que o Control Plane consome."""

    model_config = ConfigDict(extra="allow")

    id: int = Field(description="ID da oferta/ask — usado em PUT /api/v0/asks/{id}")
    machine_id: int = Field(description="ID do host físico (identidade do host).")
    host_id: int | None = None
    gpu_name: str | None = None
    num_gpus: int | None = None
    gpu_ram: int | None = Field(description="VRAM por GPU em MB (unidade da API REST).")
    gpu_total_ram: int | None = None
    cpu_name: str | None = None
    cpu_cores: int | None = None
    cpu_ram: int | None = Field(description="RAM do host em MB.")
    disk_space: float | None = Field(description="Espaço em disco do host em GB.")
    disk_bw: float | None = Field(description="Largura de banda do disco em MB/s.")
    disk_name: str | None = None
    dph_total: float | None = Field(description="Custo total USD/hora da instância.")
    dph_base: float | None = None
    min_bid: float | None = None
    reliability: float | None = None
    reliability2: float | None = None
    compute_cap: float | None = Field(description="Compute capability CUDA (ex.: 8.9 p/ 4090).")
    cuda_max_good: float | None = Field(description="Versão máxima de CUDA suportada pelo host.")
    driver_version: str | None = None
    geolocation: str | None = None
    inet_up: float | None = None
    inet_down: float | None = None
    inet_up_cost: float | None = None
    inet_down_cost: float | None = None
    storage_cost: float | None = Field(description="Custo de armazenamento USD/GB/mês.")
    storage_total_cost: float | None = None
    rentable: bool | None = None
    rented: bool | None = None
    verification: str | None = None
    is_bid: bool | None = None
    vms_enabled: bool | None = None
    gpu_arch: str | None = None
    pci_gen: float | None = None
    pcie_bw: float | None = None
    dlperf: float | None = None
    dlperf_per_dphtotal: float | None = None
    direct_port_count: int | None = None
    static_ip: bool | None = None
    avail_vol_ask_id: int | None = Field(
        description="Ask do volume disponível neste host, se houver (campo oficial)."
    )
    avail_vol_size: float | None = None
    avail_vol_dph: float | None = None


# ---------------------------------------------------------------------------
# Instância (GET /api/v0/instances/{id}/ e GET /api/v1/instances/)
# ---------------------------------------------------------------------------


class VastInstance(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: int
    actual_status: str | None = Field(
        description=(
            "null=provisionando, created, loading, running, stopped, frozen, "
            "exited, rebooting, unknown, offline (valores oficiais)."
        )
    )
    cur_state: str | None = None
    next_state: str | None = None
    intended_status: str | None = None
    label: str | None = None
    machine_id: int | None = None
    gpu_name: str | None = None
    gpu_ram: int | None = None
    num_gpus: int | None = None
    cpu_ram: int | None = None
    dph_total: float | None = None
    storage_cost: float | None = None
    image_uuid: str | None = None
    public_ipaddr: str | None = None
    ssh_host: str | None = None
    ssh_port: int | None = None
    start_date: float | None = None
    volume_info: dict[str, Any] | None = None
    extra_fs_per_gb_per_day: float | None = None


class VolumeAttachment(BaseModel):
    """Volume a associar na criação da instância (campo oficial `volume_info`).

    Forma validada no SDK oficial (build_volume_info):
    {"mount_path": str, "create_new": bool, "volume_id": int, "size"?: int, "name"?: str}
    """

    volume_id: int
    mount_path: str = "/data"
    create_new: bool = False
    size_gb: int | None = Field(default=None, description="Somente quando create_new=true.")
    name: str | None = None

    def to_api(self) -> dict[str, Any]:
        info: dict[str, Any] = {
            "mount_path": self.mount_path,
            "create_new": self.create_new,
            "volume_id": self.volume_id,
        }
        if self.size_gb is not None:
            info["size"] = self.size_gb
        if self.name is not None:
            info["name"] = self.name
        return info


class CreateInstanceRequest(BaseModel):
    """Parâmetros de criação de instância (PUT /api/v0/asks/{offer_id}/).

    Campos espelham o payload oficial validado no SDK: client_id="me",
    image (obrigatório), disk, env (dict), label, runtype, args, onstart,
    cancel_unavail, force, target_state, volume_info.
    """

    offer_id: int
    image: str = "vastai/pytorch:@vastai-automatic-tag"
    disk_gb: float = 20.0
    label: str = "localvideo-ai"
    env: dict[str, str] = Field(default_factory=dict)
    runtype: Literal["ssh", "jupyter", "args", "ssh_proxy", "ssh_direct"] = "ssh"
    args: list[str] | None = None
    onstart: str | None = None
    target_state: Literal["running", "stopped"] = "running"
    cancel_unavail: bool = Field(
        default=True,
        description="Falhar se a máquina não puder iniciar agora (evita contratos parados).",
    )
    force: bool = False
    volume: VolumeAttachment | None = None


# ---------------------------------------------------------------------------
# Volume (GET /api/v0/volumes)
# ---------------------------------------------------------------------------


class VastVolume(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: int
    machine_id: int | None = Field(description="Host físico ao qual o volume está vinculado.")
    host_id: int | None = None
    disk_space: float | None = Field(description="Capacidade em GB.")
    storage_total_cost: float | None = Field(description="Custo total de armazenamento (USD/mês).")
    status: str | None = None
    verification: str | None = None
    reliability2: float | None = None
    cpu_name: str | None = None
    cpu_arch: str | None = None
    mobo_name: str | None = None
    disk_name: str | None = None
    driver_version: str | None = None
    cuda_max_good: float | None = None
    public_ipaddr: str | None = None
    static_ip: bool | None = None
    inet_up: float | None = None
    inet_down: float | None = None
    start_date: float | None = None
    instances: list[Any] | None = None


# ---------------------------------------------------------------------------
# Cobranças (GET /api/v0/charges/)
# ---------------------------------------------------------------------------


class ChargeRow(BaseModel):
    model_config = ConfigDict(extra="allow")

    start: int | None = None
    end: int | None = None
    type: str | None = Field(description="instance | volume | serverless")
    source: str | None = Field(description="{type}-{id}, ex.: instance-12345678")
    description: str | None = None
    amount: float | None = Field(description="Cobrança total do contrato (USD).")
    metadata: dict[str, Any] | None = None


class ChargesPage(BaseModel):
    model_config = ConfigDict(extra="allow")

    success: bool = True
    count: int = 0
    total: int = 0
    next_token: str | None = None
    results: list[ChargeRow] = Field(default_factory=list)


class MonthlyUsageSummary(BaseModel):
    """Resumo agregado de uso do mês corrente, calculado a partir de charges."""

    period_start_unix: int
    period_end_unix: int
    instance_charges_usd: float = 0.0
    volume_charges_usd: float = 0.0
    other_charges_usd: float = 0.0
    total_usd: float = 0.0
    entries: list[ChargeRow] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Validações utilitárias
# ---------------------------------------------------------------------------


def validate_offer_bytes_fields(offer: VastOffer) -> list[str]:
    """Lista de problemas básicos de sanidade dos campos-chave da oferta.

    Usado antes de qualquer uso da oferta: evita propagar dados incompletos
    (ex.: gpu_ram ausente) para seleção/estimativa.
    """
    problems: list[str] = []
    if offer.gpu_ram is None:
        problems.append("gpu_ram ausente")
    if offer.dph_total is None:
        problems.append("dph_total ausente")
    if offer.machine_id is None:
        problems.append("machine_id ausente")
    return problems

