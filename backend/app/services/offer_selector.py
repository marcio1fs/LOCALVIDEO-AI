"""Seleção de ofertas (§4 do adendo).

Filtro semântico sobre ofertas já retornadas pela API, com MOTIVO de rejeição
por oferta (para diagnóstico no app) e score composto para escolher a melhor:

score = 0.45 * preço (menor melhor)
      + 0.25 * confiabilidade
      + 0.10 * bandwidth de disco
      + 0.10 * velocidade de download
      + 0.10 * dlperf_per_dphtotal

Critérios obrigatórios do adendo: VRAM, RAM, CPU, espaço em disco,
compatibilidade CUDA, confiabilidade do host, preço total, disponibilidade do
volume persistente e identidade do host físico.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from providers.vast.vast_schemas import HardwareRequirements, VastOffer

# Códigos de rejeição usados pela UI/API
R_VRAM = "VRAM_INSUFICIENTE"
R_CUDA = "CUDA_INCOMPATIVEL"
R_COMPUTE_CAP = "COMPUTE_CAP_INCOMPATIVEL"
R_RAM = "RAM_INSUFICIENTE"
R_CPU = "CPU_INSUFICIENTE"
R_DISK = "DISCO_INSUFICIENTE"
R_RELIABILITY = "CONFIABILIDADE_BAIXA"
R_PRICE = "PRECO_ACIMA_LIMITE"
R_HOST_VOLUME = "HOST_VOLUME_DIFERENTE"
R_NOT_RENTABLE = "NAO_DISPONIVEL"
R_NOT_VERIFIED = "NAO_VERIFICADA"
R_VM = "VM_NAO_SUPORTADA"
R_GPU_MODEL = "GPU_NAO_PERMITIDA"
R_DATA_MISSING = "DADOS_INCOMPLETOS"


@dataclass
class SelectionResult:
    best: VastOffer | None
    rejected: list[tuple[int, str]] = field(default_factory=list)  # (offer_id, motivo)
    considered: int = 0

    @property
    def rejection_summary(self) -> dict[str, int]:
        summary: dict[str, int] = {}
        for _, reason in self.rejected:
            summary[reason] = summary.get(reason, 0) + 1
        return summary


def _offers_usable(offer: VastOffer) -> list[str]:
    problems: list[str] = []
    if offer.gpu_ram is None or offer.dph_total is None or offer.machine_id is None:
        problems.append(R_DATA_MISSING)
    return problems


def filter_offers(
    offers: list[VastOffer],
    requirements: HardwareRequirements,
) -> SelectionResult:
    """Aplica requisitos sobre as ofertas; devolve melhor oferta + rejeitadas."""
    result = SelectionResult(best=None, rejected=[], considered=len(offers))
    survivors: list[VastOffer] = []

    for offer in offers:
        reason = _first_rejection(offer, requirements)
        if reason is None:
            survivors.append(offer)
        else:
            result.rejected.append((offer.id, reason))

    if survivors:
        prices = [o.dph_total or 0.0 for o in survivors]
        min_price, max_price = min(prices), max(prices)
        result.best = max(
            survivors,
            key=lambda o: _score(o, min_price, max_price, requirements),
        )
    return result


def _first_rejection(offer: VastOffer, req: HardwareRequirements) -> str | None:
    if _offers_usable(offer):
        return R_DATA_MISSING

    if req.exclude_vms and offer.vms_enabled:
        return R_VM
    if req.require_rentable and offer.rentable is not True:
        return R_NOT_RENTABLE
    if req.require_verified and offer.verification not in (None, "verified"):
        return R_NOT_VERIFIED
    if req.allowed_gpus and (offer.gpu_name not in req.allowed_gpus):
        return R_GPU_MODEL
    if offer.gpu_ram is not None and offer.gpu_ram < req.min_vram_mb:
        return R_VRAM
    if offer.num_gpus is not None and offer.num_gpus < req.min_gpu_count:
        return R_CPU  # quantidade de GPUs insuficiente — mantemos código simples
    if offer.cpu_ram is not None and offer.cpu_ram < req.min_cpu_ram_mb:
        return R_RAM
    if offer.cpu_cores is not None and offer.cpu_cores < req.min_cpu_cores:
        return R_CPU
    if offer.disk_space is not None and offer.disk_space < req.min_disk_gb:
        return R_DISK
    if offer.reliability is not None and offer.reliability < req.min_reliability:
        return R_RELIABILITY
    if req.min_compute_cap is not None and offer.compute_cap is not None:
        if offer.compute_cap < req.min_compute_cap:
            return R_COMPUTE_CAP
    if req.min_cuda_version is not None and offer.cuda_max_good is not None:
        if offer.cuda_max_good < req.min_cuda_version:
            return R_CUDA
    if req.max_dph_total is not None and offer.dph_total is not None:
        if offer.dph_total > req.max_dph_total:
            return R_PRICE
    if req.volume_machine_id is not None and offer.machine_id != req.volume_machine_id:
        return R_HOST_VOLUME
    return None


def _score(offer: VastOffer, min_price: float, max_price: float, req: HardwareRequirements) -> float:
    """Score composto (0..1): preço (normalizado entre as sobreviventes),
    confiabilidade, bandwidth de disco, rede e desempenho por dólar."""
    price = offer.dph_total or 0.0
    span = max_price - min_price
    if span > 0:
        price_score = 1.0 - (price - min_price) / span
    else:
        price_score = 1.0

    reliability = min(offer.reliability or 0.0, 1.0)
    disk_bw_score = min((offer.disk_bw or 0.0) / 1500.0, 1.0)
    inet_score = min((offer.inet_down or 0.0) / 2000.0, 1.0)
    perf_score = min((offer.dlperf_per_dphtotal or 0.0) / 40.0, 1.0)

    return (
        0.45 * price_score
        + 0.25 * reliability
        + 0.10 * disk_bw_score
        + 0.10 * inet_score
        + 0.10 * perf_score
    )


def describe(offer: VastOffer) -> dict[str, Any]:
    """Resumo legível de uma oferta para respostas de API."""
    return {
        "offer_id": offer.id,
        "machine_id": offer.machine_id,
        "gpu_name": offer.gpu_name,
        "num_gpus": offer.num_gpus,
        "vram_mb": offer.gpu_ram,
        "cpu_ram_mb": offer.cpu_ram,
        "cpu_cores": offer.cpu_cores,
        "disk_gb": offer.disk_space,
        "cuda_max_good": offer.cuda_max_good,
        "compute_cap": offer.compute_cap,
        "reliability": offer.reliability,
        "dph_total_usd": offer.dph_total,
        "geolocation": offer.geolocation,
        "has_volume_ask": offer.avail_vol_ask_id is not None,
    }
