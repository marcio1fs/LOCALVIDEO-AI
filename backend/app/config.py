"""Configuração central do Control Plane LocalVideo AI.

Todas as variáveis podem ser definidas por ambiente (prefixo LV_) ou por um
arquivo `.env` na raiz do projeto. Veja `.env.example` para a lista completa
e comentada.

REGRAS DE SEGURANÇA (adendo §10):
- A chave da Vast.ai existe SOMENTE no servidor de controle e nunca é
  serializada em logs, respostas de API ou objetos enviados ao desktop.
- As chaves da API própria (cliente/admin) nunca recebem valor padrão;
  sem chave configurada, o serviço entra em modo "fechado" (fail-closed).
- Operações que geram cobrança exigem VAST_ENABLE_MUTATIONS=true,
  além de autenticação admin e verificação de orçamento.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuração do Control Plane."""

    model_config = SettingsConfigDict(
        env_prefix="LV_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ------------------------------------------------------------------
    # Identidade do serviço
    # ------------------------------------------------------------------
    app_name: str = "LocalVideo AI Control Plane"
    environment: str = Field(
        default="development",
        description="development | staging | production",
    )
    log_level: str = "INFO"

    # ------------------------------------------------------------------
    # Autenticação da API própria do LocalVideo AI (§9/§10)
    # ------------------------------------------------------------------
    localvideo_api_key: str | None = Field(
        default=None,
        description="Chave usada pelo desktop client para chamar o Control Plane.",
    )
    localvideo_admin_api_key: str | None = Field(
        default=None,
        description=(
            "Chave admin para operações que geram cobrança (start/stop/destroy). "
            "Se não definida, a chave de cliente é aceita com aviso em dev."
        ),
    )
    allow_insecure_dev: bool = Field(
        default=False,
        description=(
            "Se true e nenhuma chave estiver configurada, as rotas autenticadas "
            "respondem 503 igualmente — mas /health e /docs continuam acessíveis. "
            "Nunca habilite rotas abertas em produção."
        ),
    )

    # ------------------------------------------------------------------
    # Vast.ai (§3)
    # ------------------------------------------------------------------
    vast_api_key: str | None = Field(
        default=None,
        description="Chave admin da Vast.ai — exclusiva do servidor de controle.",
    )
    vast_server_url: str = "https://console.vast.ai"
    vast_enable_mutations: bool = Field(
        default=False,
        description=(
            "PORTÃO DE COBRANÇA. Se false, nenhuma operação que crie/altere/"
            "destrua instâncias ou volumes é executada (resposta 409 na API). "
            "Padrão: false, inclusive em produção — exige ativação explícita."
        ),
    )
    vast_retry_attempts: int = 3
    vast_backoff_base_seconds: float = 0.15
    vast_backoff_factor: float = 1.5
    vast_max_retry_after_seconds: float = 60.0
    vast_timeout_seconds: float = 120.0
    vast_idempotency_ttl_seconds: int = 300
    vast_max_pages_instances: int = 8

    # ------------------------------------------------------------------
    # Controle financeiro (§8)
    # ------------------------------------------------------------------
    gpu_monthly_budget_brl: float = Field(
        default=100.0,
        description="Orçamento mensal em reais (configurável no app).",
    )
    usd_to_brl_rate: float = Field(
        default=5.40,
        description="Taxa de conversão USD->BRL usada nas estimativas. Atualizável.",
    )
    budget_alert_threshold: float = 0.70
    budget_block_threshold: float = 0.90
    estimated_session_hours: float = Field(
        default=1.0,
        description="Horas estimadas por sessão para reserva de orçamento.",
    )
    storage_reserve_brl: float = Field(
        default=5.0,
        description="Reserva mínima de orçamento para armazenamento/tráfego.",
    )

    # ------------------------------------------------------------------
    # GPU Manager / Idle Manager (§6/§7)
    # ------------------------------------------------------------------
    gpu_auto_start: bool = True
    gpu_auto_stop: bool = True
    gpu_idle_timeout_minutes: int = 10
    gpu_max_concurrent_jobs: int = 1
    instance_poll_interval_seconds: float = 5.0
    instance_ready_timeout_seconds: float = 900.0

    # ------------------------------------------------------------------
    # Perfil de hardware editável (§4) — JSON ou valores individuais
    # ------------------------------------------------------------------
    gpu_pref_min_vram_mb: int = 24576  # RTX 4090 = 24 GB (em MB, unidade da API)
    gpu_pref_min_ram_mb: int = 32768   # RAM do host (cpu_ram em MB na API)
    gpu_pref_min_disk_gb: float = 60.0
    gpu_pref_min_reliability: float = 0.98
    gpu_pref_min_compute_cap: float = 8.0  # Ampere+ (8.6, 8.9, 9.0 ...)
    gpu_pref_cuda_min: float = 11.8
    gpu_pref_allowed_gpus: list[str] = Field(
        default_factory=lambda: [
            "RTX 4090",
            "RTX 4090D",
            "RTX 5090",
            "A100 PCIE",
            "A100 SXM4",
            "H100",
            "H100 SXM",
            "L40S",
        ],
        description="GPUs aceitas por padrão. Editável no app (§4: não fixar 4090).",
    )
    gpu_pref_max_dph_total: float | None = Field(
        default=None,
        description="Teto de preço USD/hora para seleção automática (opcional).",
    )

    # ------------------------------------------------------------------
    # Armazenamento persistente (§5)
    # ------------------------------------------------------------------
    data_dir: str = "./data"
    volume_mount_path: str = "/data"
    volume_default_size_gb: int = 100

    # ------------------------------------------------------------------
    # Segurança HTTP (§10)
    # ------------------------------------------------------------------
    rate_limit_requests_per_minute: int = 60
    rate_limit_burst: int = 20
    max_request_body_bytes: int = 10 * 1024 * 1024  # 10 MB
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:1420", "http://localhost:5173"],
        description="Origens do desktop Tauri em dev. Produção: configurar explicitamente.",
    )

    @field_validator("cors_origins", "gpu_pref_allowed_gpus", mode="before")
    @classmethod
    def _parse_json_list(cls, value: Any) -> Any:
        """Permite definir listas via env como JSON (ex.: '["RTX 4090","L40S"]')."""
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                if isinstance(parsed, list):
                    return parsed
            except json.JSONDecodeError:
                return [item.strip() for item in value.split(",") if item.strip()]
        return value

    # ------------------------------------------------------------------
    # Derivados
    # ------------------------------------------------------------------
    @property
    def mutations_enabled(self) -> bool:
        """Portão global de operações que geram cobrança na Vast.ai."""
        return self.vast_enable_mutations is True and self.vast_api_key is not None

    @property
    def vast_configured(self) -> bool:
        return self.vast_api_key is not None and len(self.vast_api_key) > 0


@lru_cache
def get_settings() -> Settings:
    """Instância única (cacheada) das configurações."""
    return Settings()


def describe_safe(settings: Settings) -> dict[str, Any]:
    """Resumo seguro da configuração, SEM segredos (para /health e logs)."""
    return {
        "environment": settings.environment,
        "localvideo_api_key_configured": settings.localvideo_api_key is not None,
        "localvideo_admin_api_key_configured": settings.localvideo_admin_api_key is not None,
        "vast_api_key_configured": settings.vast_configured,
        "vast_mutations_enabled": settings.mutations_enabled,
        "vast_server_url": settings.vast_server_url,
        "gpu_monthly_budget_brl": settings.gpu_monthly_budget_brl,
        "usd_to_brl_rate": settings.usd_to_brl_rate,
        "gpu_auto_start": settings.gpu_auto_start,
        "gpu_auto_stop": settings.gpu_auto_stop,
        "gpu_idle_timeout_minutes": settings.gpu_idle_timeout_minutes,
        "gpu_max_concurrent_jobs": settings.gpu_max_concurrent_jobs,
        "rate_limit_requests_per_minute": settings.rate_limit_requests_per_minute,
    }
