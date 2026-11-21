"""Rotas /api/v1/gpu — status, start, stop, offers, cost-estimate, usage.

Todas as rotas exigem autenticação (§9). Operações de criação/parada exigem
chave admin e são protegidas contra duplicação/concorrência pelo GPU Manager
(asyncio.Lock + portão de mutações + orçamento).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.schemas.gpu import (
    BudgetResponse,
    BudgetUpdateRequest,
    GpuCostEstimateResponse,
    GpuOffersQuery,
    GpuStartRequest,
    GpuStartResponse,
    GpuStatusResponse,
    GpuStopRequest,
    GpuUsageResponse,
)
from app.security.audit import AuditLogger
from app.security.auth import AuthContext, audit_fields, require_admin_auth, require_auth
from providers.vast import (
    HardwareRequirements,
    VastError,
    VastRateLimitError,
)
from providers.vast.vast_exceptions import VastAuthError

logger = logging.getLogger("localvideo.api.gpu")

router = APIRouter(prefix="/api/v1/gpu", tags=["GPU Cloud"])


def _services(request: Request):
    return request.app.state


@router.get("/status", response_model=GpuStatusResponse)
async def gpu_status(
    request: Request,
    context: AuthContext = Depends(require_auth),
) -> GpuStatusResponse:
    data = await _services(request).gpu_manager.status()
    return GpuStatusResponse(**data)


@router.post("/start", response_model=GpuStartResponse)
async def gpu_start(
    payload: GpuStartRequest,
    request: Request,
    context: AuthContext = Depends(require_admin_auth),
) -> GpuStartResponse:
    state = _services(request)
    audit: AuditLogger = state.audit_logger
    audit.record(
        actor=context.label,
        action="gpu.start",
        result="accepted",
        details={"volume_id": payload.volume_id, "estimated_hours": payload.estimated_hours},
    )
    try:
        outcome = await state.gpu_manager.start(
            payload.requirements,
            volume_id=payload.volume_id,
            estimated_hours=payload.estimated_hours,
            confirm_cost=payload.confirm_cost,
        )
    except VastAuthError as exc:
        audit.record(actor=context.label, action="gpu.start", result="upstream_auth_error")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": "vast_auth_error",
                "message": "Chave da Vast.ai rejeitada pelo provedor. "
                "Verifique LV_VAST_API_KEY no servidor de controle.",
            },
        ) from exc
    except VastRateLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    except VastError as exc:
        audit.record(actor=context.label, action="gpu.start", result="error", details={"code": exc.code})
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": exc.code, "message": exc.message},
        ) from exc

    audit.record(
        actor=context.label,
        action="gpu.start",
        result=outcome.state.value,
        details={"instance_id": outcome.session.instance_id if outcome.session else None},
    )
    return GpuStartResponse(
        state=outcome.state.value,
        message=outcome.message,
        instance_id=outcome.session.instance_id if outcome.session else None,
        errors=outcome.errors,
        gpu=state.gpu_manager.gpu_summary(),
    )


@router.post("/stop")
async def gpu_stop(
    payload: GpuStopRequest,
    request: Request,
    context: AuthContext = Depends(require_admin_auth),
) -> dict:
    state = _services(request)
    audit: AuditLogger = state.audit_logger
    audit.record(actor=context.label, action="gpu.stop", result="accepted", details={"mode": payload.mode})
    try:
        result = await state.gpu_manager.stop(
            mode=payload.mode,
            data_persisted_confirmed=payload.data_persisted_confirmed,
        )
    except VastError as exc:
        audit.record(actor=context.label, action="gpu.stop", result="error", details={"code": exc.code})
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    audit.record(actor=context.label, action="gpu.stop", result=result.get("state", "?"))
    return result


@router.post("/offers")
async def gpu_offers(
    payload: GpuOffersQuery,
    request: Request,
    context: AuthContext = Depends(require_auth),
) -> dict:
    """Consulta ofertas compatíveis (somente leitura; não cria nada)."""
    state = _services(request)
    if not state.settings.vast_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "vast_key_missing",
                "message": "VAST_API_KEY não configurada no servidor de controle.",
            },
        )
    try:
        plan = await state.gpu_manager.plan_provision(
            payload.requirements,
            estimated_hours=payload.estimated_hours,
        )
    except VastAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "vast_auth_error", "message": exc.message},
        ) from exc
    except VastRateLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    except VastError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    return state.gpu_manager.public_plan(plan)


@router.get("/cost-estimate", response_model=GpuCostEstimateResponse)
async def gpu_cost_estimate(
    request: Request,
    context: AuthContext = Depends(require_auth),
    estimated_hours: float | None = None,
    volume_id: int | None = None,
) -> GpuCostEstimateResponse:
    state = _services(request)
    if not state.settings.vast_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "vast_key_missing",
                "message": "VAST_API_KEY não configurada no servidor de controle.",
            },
        )
    plan = await state.gpu_manager.plan_provision(
        None,
        volume_id=volume_id,
        estimated_hours=estimated_hours,
    )
    public = state.gpu_manager.public_plan(plan)
    return GpuCostEstimateResponse(
        feasible=public.get("feasible", False),
        offer=public.get("offer"),
        cost_estimate=public.get("cost_estimate"),
        volume=public.get("volume"),
        considered=public.get("considered", 0),
        rejection_summary=public.get("rejection_summary", {}),
        message=public.get("message"),
    )


@router.get("/usage", response_model=GpuUsageResponse)
async def gpu_usage(
    request: Request,
    context: AuthContext = Depends(require_auth),
) -> GpuUsageResponse:
    state = _services(request)
    manager_status = await state.gpu_manager.status()
    ledger = await state.cost_manager.ledger()
    history = await state.gpu_manager.history()
    return GpuUsageResponse(
        budget=manager_status["budget"],
        ledger=ledger,
        history=history,
    )


@router.patch("/budget", response_model=BudgetResponse)
async def update_budget(
    payload: BudgetUpdateRequest,
    request: Request,
    context: AuthContext = Depends(require_admin_auth),
) -> BudgetResponse:
    """Limite mensal configurável no painel (§11). Exige chave admin.

    Persistido em `data/cost_settings.json` (PostgreSQL na Fase 6) e auditado.
    """
    state = _services(request)
    state.audit_logger.record(
        actor=context.label,
        action="gpu.budget_update",
        result="accepted",
        details={
            "monthly_budget_brl": payload.monthly_budget_brl,
            "usd_to_brl_rate": payload.usd_to_brl_rate,
        },
    )
    budget = await state.cost_manager.update_budget(
        monthly_budget_brl=payload.monthly_budget_brl,
        usd_to_brl_rate=payload.usd_to_brl_rate,
    )
    state.audit_logger.record(actor=context.label, action="gpu.budget_update", result="ok")
    return BudgetResponse(budget=budget.to_dict())


@router.get("/hardware-profile")
async def hardware_profile(request: Request, context: AuthContext = Depends(require_auth)) -> dict:
    """Perfil de hardware padrão editável (§4: não fixar RTX 4090)."""
    settings = _services(request).settings
    profile = HardwareRequirements(
        allowed_gpus=settings.gpu_pref_allowed_gpus,
        min_vram_mb=settings.gpu_pref_min_vram_mb,
        min_cpu_ram_mb=settings.gpu_pref_min_ram_mb,
        min_disk_gb=settings.gpu_pref_min_disk_gb,
        min_reliability=settings.gpu_pref_min_reliability,
        min_compute_cap=settings.gpu_pref_min_compute_cap,
        min_cuda_version=settings.gpu_pref_cuda_min,
        max_dph_total=settings.gpu_pref_max_dph_total,
    )
    return profile.model_dump()


__all__ = ["router", "audit_fields"]
