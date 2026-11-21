"""Fábrica da aplicação FastAPI do Control Plane LocalVideo AI.

- Autenticação por chave própria em todas as rotas protegidas (fail-closed).
- Rate limiting em memória (§10).
- Tratamento de erros Vast.ai com envelope estável.
- Serviços montados em app.state (injeção simples e testável).
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import api_router
from app.config import Settings, describe_safe, get_settings
from app.security.audit import AuditLogger
from app.security.auth import KeyVerifier
from app.security.rate_limit import install_rate_limit
from app.services.cost_manager import CostManager
from app.services.gpu_manager import GpuManager
from app.services.storage_registry import StorageRegistry
from providers.vast import (
    MutationGate,
    VastBillingService,
    VastClientConfig,
    VastHttpClient,
    VastInstancesService,
    VastOffersService,
    VastVolumesService,
)

logger = logging.getLogger("localvideo")


def _configure_logging(level: str) -> None:
    logging.basicConfig(level=getattr(logging, level.upper(), logging.INFO))
    logging.getLogger("httpx").setLevel(logging.WARNING)


def build_services(settings: Settings) -> dict:
    """Constrói a árvore de serviços a partir da configuração."""
    client_config = VastClientConfig(
        api_key=settings.vast_api_key,
        server_url=settings.vast_server_url,
        retry_attempts=settings.vast_retry_attempts,
        backoff_base_seconds=settings.vast_backoff_base_seconds,
        backoff_factor=settings.vast_backoff_factor,
        max_retry_after_seconds=settings.vast_max_retry_after_seconds,
        timeout_seconds=settings.vast_timeout_seconds,
        idempotency_ttl_seconds=settings.vast_idempotency_ttl_seconds,
    )
    http = VastHttpClient(client_config)

    gate = MutationGate(
        enabled=settings.mutations_enabled,
        reason=(
            "Operações que geram cobrança na Vast.ai estão desabilitadas. "
            "Para habilitar: defina LV_VAST_API_KEY e LV_VAST_ENABLE_MUTATIONS=true "
            "no servidor de controle e autentique com a chave admin."
        ),
    )
    cost_manager = CostManager(
        data_dir=settings.data_dir,
        monthly_budget_brl=settings.gpu_monthly_budget_brl,
        usd_to_brl_rate=settings.usd_to_brl_rate,
        alert_threshold=settings.budget_alert_threshold,
        block_threshold=settings.budget_block_threshold,
        storage_reserve_brl=settings.storage_reserve_brl,
    )
    storage_registry = StorageRegistry(data_dir=settings.data_dir)

    return {
        "settings": settings,
        "http": http,
        "vast_offers": VastOffersService(http),
        "vast_instances": VastInstancesService(http, gate),
        "vast_volumes": VastVolumesService(http, gate),
        "vast_billing": VastBillingService(http),
        "cost_manager": cost_manager,
        "storage_registry": storage_registry,
        "audit_logger": AuditLogger(data_dir=settings.data_dir),
        "verifier": KeyVerifier(settings),
    }


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    _configure_logging(settings.log_level)

    services = build_services(settings)
    gpu_manager = GpuManager(
        settings=settings,
        http=services["http"],
        offers=services["vast_offers"],
        instances=services["vast_instances"],
        volumes=services["vast_volumes"],
        billing=services["vast_billing"],
        cost_manager=services["cost_manager"],
        storage_registry=services["storage_registry"],
        worker_probe=None,  # Fase 2: sonda real de worker (validação de prontidão)
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        summary = describe_safe(settings)
        logger.info("LocalVideo AI Control Plane iniciado: %s", summary)
        if not settings.localvideo_api_key:
            logger.warning(
                "LV_LOCALVIDEO_API_KEY não configurada: rotas autenticadas respondem 503 (fail-closed)."
            )
        yield
        await services["http"].aclose()

    app = FastAPI(
        title=settings.app_name,
        description=(
            "Control Plane do LocalVideo AI: GPU sob demanda (Vast.ai), armazenamento "
            "persistente e controle financeiro. A chave da Vast.ai nunca sai do servidor.\n\n"
            "**Fase 1**: adaptador Vast.ai, GPU Manager (estados), Cost Manager, Storage "
            "Registry e rotas de leitura. Pipeline de geração real: Fase 3."
        ),
        version="0.1.0",
        lifespan=lifespan,
    )

    app.state.settings = settings
    app.state.gpu_manager = gpu_manager
    for name, service in services.items():
        setattr(app.state, name, service)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["X-API-Key", "Authorization", "Content-Type"],
        max_age=600,
    )
    install_rate_limit(
        app,
        requests_per_minute=settings.rate_limit_requests_per_minute,
        burst=settings.rate_limit_burst,
    )

    app.include_router(api_router)

    # ------------------------------------------------------------------
    # Tratamento de erros com envelope estável
    # ------------------------------------------------------------------
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        detail = exc.detail
        if isinstance(detail, dict):
            payload = {"error": detail}
        else:
            payload = {"error": {"code": "http_error", "message": str(detail)}}
        return JSONResponse(status_code=exc.status_code, content=payload, headers=exc.headers)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        logger.exception("Erro não tratado em %s: %s", request.url.path, exc)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"error": {"code": "internal_error", "message": "Erro interno do servidor."}},
        )

    return app


app = create_app()
