"""GPU Manager — orquestração da sessão de GPU (§6 do adendo).

Máquina de estados obrigatória:
  OFFLINE, STARTING, PROVISIONING, CHECKING, READY, BUSY, IDLE, STOPPING,
  ERROR, RECOVERING, HOST_UNAVAILABLE, VOLUME_UNAVAILABLE,
  BUDGET_LIMIT_REACHED

Pipeline de início (guardado por asyncio.Lock — proteção contra duplicação e
concorrência, §9):
  1. autenticação (feita pela camada de API)
  2. verificação do orçamento (Cost Manager)
  3. verificação de fila (Job Manager entra na Fase 3; fila sempre vazia aqui)
  4. consulta de instância ativa
  5. consulta de ofertas compatíveis
  6. verificação do host do volume (afinidade física)
  7. estimativa de custo + reserva
  8. criação da instância (idempotente)
  9. associação do volume persistente (volume_info)
  10/11. verificação de GPU/CUDA/disco -> poll de running
  12. inicialização/validação do worker (Fase 2 — sonda injetável)
  13. READY somente com worker validado
  14. liberação da tarefa (Job Manager, Fase 3)

"A prontidão depende da validação real do serviço de inferência": sem sonda
de worker configurada, o manager NUNCA declara READY (fica em CHECKING).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from providers.vast import (
    CreateInstanceRequest,
    HardwareRequirements,
    VastBillingService,
    VastError,
    VastHttpClient,
    VastInstance,
    VastInstanceNotFoundError,
    VastInstancesService,
    VastInstanceUnrecoverableError,
    VastOffer,
    VastOffersService,
    VastOfferUnavailableError,
    VastRateLimitError,
    VastVolumeError,
    VastVolumeHostMismatchError,
    VastVolumesService,
    VolumeAttachment,
)

from .cost_manager import CostManager, StartDecision
from .offer_selector import SelectionResult, describe, filter_offers
from .storage_registry import StorageRegistry, VolumeRecord, VolumeState

logger = logging.getLogger("localvideo.gpu")


class GpuState(StrEnum):
    OFFLINE = "OFFLINE"
    STARTING = "STARTING"
    PROVISIONING = "PROVISIONING"
    CHECKING = "CHECKING"
    READY = "READY"
    BUSY = "BUSY"
    IDLE = "IDLE"
    STOPPING = "STOPPING"
    ERROR = "ERROR"
    RECOVERING = "RECOVERING"
    HOST_UNAVAILABLE = "HOST_UNAVAILABLE"
    VOLUME_UNAVAILABLE = "VOLUME_UNAVAILABLE"
    BUDGET_LIMIT_REACHED = "BUDGET_LIMIT_REACHED"


# Transições válidas (máquina de estados defensiva)
TRANSITIONS: dict[GpuState, set[GpuState]] = {
    GpuState.OFFLINE: {GpuState.STARTING, GpuState.ERROR, GpuState.BUDGET_LIMIT_REACHED, GpuState.RECOVERING},
    GpuState.STARTING: {
        GpuState.PROVISIONING,
        GpuState.BUDGET_LIMIT_REACHED,
        GpuState.VOLUME_UNAVAILABLE,
        GpuState.HOST_UNAVAILABLE,
        GpuState.ERROR,
        GpuState.OFFLINE,
    },
    GpuState.PROVISIONING: {
        GpuState.CHECKING,
        GpuState.ERROR,
        GpuState.HOST_UNAVAILABLE,
        GpuState.VOLUME_UNAVAILABLE,
    },
    GpuState.CHECKING: {
        GpuState.READY,
        GpuState.ERROR,
        GpuState.RECOVERING,
        GpuState.STOPPING,
        GpuState.HOST_UNAVAILABLE,
        GpuState.VOLUME_UNAVAILABLE,
    },
    GpuState.READY: {GpuState.BUSY, GpuState.IDLE, GpuState.STOPPING, GpuState.ERROR},
    GpuState.BUSY: {GpuState.IDLE, GpuState.READY, GpuState.STOPPING, GpuState.ERROR},
    GpuState.IDLE: {GpuState.BUSY, GpuState.STOPPING, GpuState.ERROR},
    GpuState.STOPPING: {GpuState.OFFLINE, GpuState.ERROR},
    GpuState.ERROR: {GpuState.OFFLINE, GpuState.STARTING, GpuState.RECOVERING, GpuState.STOPPING},
    GpuState.RECOVERING: {GpuState.READY, GpuState.OFFLINE, GpuState.ERROR},
    GpuState.HOST_UNAVAILABLE: {GpuState.OFFLINE, GpuState.STARTING, GpuState.RECOVERING, GpuState.STOPPING},
    GpuState.VOLUME_UNAVAILABLE: {GpuState.OFFLINE, GpuState.STARTING, GpuState.STOPPING},
    GpuState.BUDGET_LIMIT_REACHED: {GpuState.OFFLINE, GpuState.STARTING, GpuState.STOPPING},
}


class WorkerProbeResult:
    def __init__(self, ok: bool, message: str, details: dict[str, Any] | None = None) -> None:
        self.ok = ok
        self.message = message
        self.details = details or {}


WorkerProbe = Callable[[VastInstance, VastOffer], Awaitable[WorkerProbeResult]]


@dataclass
class GpuSession:
    instance_id: int | None = None
    offer: VastOffer | None = None
    volume_id: int | None = None
    started_at: float | None = None
    reserved_usd: float = 0.0
    label: str = "localvideo-ai"

    @property
    def elapsed_hours(self) -> float:
        if self.started_at is None:
            return 0.0
        return max((time.time() - self.started_at) / 3600.0, 0.0)

    def accrual_usd(self) -> float:
        if self.offer is None or self.offer.dph_total is None:
            return 0.0
        return self.offer.dph_total * self.elapsed_hours


@dataclass
class StartOutcome:
    state: GpuState
    message: str
    session: GpuSession | None = None
    selection: SelectionResult | None = None
    errors: list[str] = field(default_factory=list)


class GpuManager:
    """Serviço central de sessão de GPU sob demanda."""

    def __init__(
        self,
        *,
        settings: Any,
        http: VastHttpClient,
        offers: VastOffersService,
        instances: VastInstancesService,
        volumes: VastVolumesService,
        billing: VastBillingService,
        cost_manager: CostManager,
        storage_registry: StorageRegistry,
        worker_probe: WorkerProbe | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.settings = settings
        self.http = http
        self.offers = offers
        self.instances = instances
        self.volumes = volumes
        self.billing = billing
        self.cost = cost_manager
        self.registry = storage_registry
        # Fase 2 injeta a sonda real (validação CUDA/worker). Sem sonda,
        # nunca declaramos READY (§6 passo 13).
        self.worker_probe = worker_probe
        self._clock = clock or time.time
        self._lock = asyncio.Lock()
        self.state = GpuState.OFFLINE
        self.session = GpuSession()
        self.last_message = "Sessão de GPU inativa."
        self._queue_size = 0  # Job Manager (Fase 3)
        self._history: list[dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Máquina de estados
    # ------------------------------------------------------------------
    def _transition(self, new_state: GpuState, message: str) -> None:
        allowed = TRANSITIONS.get(self.state, set())
        if new_state != self.state and new_state not in allowed:
            logger.warning(
                "Transição de GPU inválida %s -> %s (permitidas: %s). Mantendo %s.",
                self.state, new_state, sorted(s.value for s in allowed), self.state,
            )
            raise RuntimeError(f"Transição de estado inválida: {self.state} -> {new_state}")
        previous = self.state
        self.state = new_state
        self.last_message = message
        self._history.append(
            {
                "ts": self._clock(),
                "from": previous.value,
                "state": new_state.value,
                "message": message,
            }
        )
        logger.info("GPU state -> %s : %s", new_state.value, message)

    # ------------------------------------------------------------------
    # Consultas
    # ------------------------------------------------------------------
    async def status(self) -> dict[str, Any]:
        session_accrual_brl = self.cost.usd_to_brl(self.session.accrual_usd())
        # A reserva já cobre a sessão estimada; só o EXCEDENTE de acúmulo
        # (sessão rodando além do estimado) entra no comprometimento do mês.
        reserved_brl = self.cost.usd_to_brl(self.session.reserved_usd)
        excess_brl = max(session_accrual_brl - reserved_brl, 0.0)
        budget = await self.cost.budget_status(session_accrual_brl=excess_brl)
        return {
            "state": self.state.value,
            "provider": "vast.ai",
            "provider_configured": self.settings.vast_configured,
            "mutations_enabled": self.settings.mutations_enabled,
            "message": self.last_message,
            "instance_id": self.session.instance_id,
            "gpu": self._gpu_summary(),
            "volume_id": self.session.volume_id,
            "session": {
                "started_at": self.session.started_at,
                "elapsed_hours": round(self.session.elapsed_hours, 3),
                "accrual_usd": round(self.session.accrual_usd(), 4),
                "accrual_brl": round(session_accrual_brl, 2),
            },
            "budget": budget.to_dict(),
            "queue_size": self._queue_size,
            "max_concurrent_jobs": self.settings.gpu_max_concurrent_jobs,
            "idle_timeout_minutes": self.settings.gpu_idle_timeout_minutes,
        }

    def _gpu_summary(self) -> dict[str, Any] | None:
        offer = self.session.offer
        if offer is None:
            return None
        return {
            "offer_id": offer.id,
            "machine_id": offer.machine_id,
            "gpu_name": offer.gpu_name,
            "vram_mb": offer.gpu_ram,
            "dph_total_usd": offer.dph_total,
            "reliability": offer.reliability,
        }

    def gpu_summary(self) -> dict[str, Any] | None:
        """Alias público para a camada de API."""
        return self._gpu_summary()

    async def history(self) -> list[dict[str, Any]]:
        return list(reversed(self._history[-100:]))

    # ------------------------------------------------------------------
    # Planejamento (somente leitura — sem criação)
    # ------------------------------------------------------------------
    async def plan_provision(
        self,
        requirements: HardwareRequirements | None = None,
        *,
        volume_id: int | None = None,
        estimated_hours: float | None = None,
    ) -> dict[str, Any]:
        """Consulta ofertas e devolve plano (melhor oferta, custo estimado,
        afinidade com volume) SEM criar nada."""
        req = requirements or self._default_requirements()
        hours = estimated_hours or self.settings.estimated_session_hours

        volume_record = await self._resolve_volume(volume_id)
        if volume_record is not None:
            req.volume_machine_id = volume_record.machine_id

        offers = await self.offers.search(req)
        selection = filter_offers(offers, req)

        plan: dict[str, Any] = {
            "requirements": req.model_dump(),
            "considered": selection.considered,
            "rejection_summary": selection.rejection_summary,
            "volume": self.registry.to_public(volume_record) if volume_record else None,
        }

        if selection.best is None:
            plan["feasible"] = False
            plan["message"] = "Nenhuma oferta compatível encontrada para os requisitos atuais."
            if selection.rejection_summary.get("HOST_VOLUME_DIFERENTE"):
                plan["volume_unavailable_hint"] = (
                    "Ofertas existem, mas não no host físico do volume registrado."
                )
            return plan

        best = selection.best
        estimate = self.cost.estimate_session(
            hourly_price_usd=best.dph_total or 0.0,
            hours=hours,
            storage_monthly_usd=volume_record.storage_monthly_usd if volume_record else 0.0,
        )
        plan.update(
            {
                "feasible": True,
                "offer": describe(best),
                "cost_estimate": estimate,
                "top_offers": [describe(o) for o in selection.ranked[:8]],
            }
        )
        plan["_offer_obj"] = best  # objeto interno (removido antes de expor via API)
        return plan

    @staticmethod
    def public_plan(plan: dict[str, Any]) -> dict[str, Any]:
        """Remove chaves internas (prefixo '_') para resposta de API."""
        return {k: v for k, v in plan.items() if not k.startswith("_")}

    # ------------------------------------------------------------------
    # Início (pipeline completo)
    # ------------------------------------------------------------------
    async def start(
        self,
        requirements: HardwareRequirements | None = None,
        *,
        volume_id: int | None = None,
        estimated_hours: float | None = None,
        confirm_cost: bool = True,
    ) -> StartOutcome:
        """Provisiona a sessão completa. Requer portão de mutações habilitado.

        `confirm_cost` deve ser true: o usuário/aplicativo reconhece o custo
        estimado antes de qualquer cobrança (§14).
        """
        if not confirm_cost:
            return StartOutcome(
                state=self.state,
                message="Início negado: confirmação de custo obrigatória (confirm_cost=false).",
                errors=["confirm_cost deve ser true para operações que geram cobrança."],
            )

        async with self._lock:
            if self.state in (GpuState.STARTING, GpuState.PROVISIONING, GpuState.CHECKING, GpuState.STOPPING):
                return StartOutcome(
                    state=self.state,
                    message="Provisionamento já em andamento; segunda solicitação ignorada.",
                    session=self.session,
                    errors=["gpu_busy"],
                )
            if self.state in (GpuState.READY, GpuState.BUSY, GpuState.IDLE):
                return StartOutcome(
                    state=self.state,
                    message=(
                        f"Sessão de GPU já ativa (instância {self.session.instance_id}); "
                        "solicitação ignorada para evitar duplicação de cobrança."
                    ),
                    session=self.session,
                    errors=["session_already_active"],
                )

            req = requirements or self._default_requirements()
            hours = estimated_hours or self.settings.estimated_session_hours

            try:
                return await self._start_pipeline(req, volume_id=volume_id, hours=hours)
            except VastRateLimitError as exc:
                self._fail(GpuState.ERROR, f"Limite de requisições Vast.ai: {exc.message}")
                return StartOutcome(self.state, self.last_message, errors=["rate_limited"])
            except VastOfferUnavailableError as exc:
                self._fail(GpuState.HOST_UNAVAILABLE, f"Oferta indisponível: {exc.message}")
                return StartOutcome(self.state, self.last_message, errors=["offer_unavailable"])
            except VastInstanceUnrecoverableError as exc:
                self._fail(GpuState.ERROR, exc.message)
                return StartOutcome(self.state, self.last_message, errors=["instance_poll_trap"])
            except VastVolumeHostMismatchError as exc:
                self._fail(GpuState.VOLUME_UNAVAILABLE, exc.message)
                return StartOutcome(self.state, self.last_message, errors=["volume_host_mismatch"])
            except VastVolumeError as exc:
                self._fail(GpuState.VOLUME_UNAVAILABLE, exc.message)
                return StartOutcome(self.state, self.last_message, errors=["volume_error"])
            except VastError as exc:
                self._fail(GpuState.ERROR, f"Erro Vast.ai: {exc.message}")
                return StartOutcome(self.state, self.last_message, errors=[exc.code])

    async def _start_pipeline(
        self,
        req: HardwareRequirements,
        *,
        volume_id: int | None,
        hours: float,
    ) -> StartOutcome:
        # (1) Autenticação: realizada pela camada API; aqui garantimos chave Vast.
        if not self.settings.vast_configured:
            self._fail(GpuState.OFFLINE, "VAST_API_KEY não configurada no servidor de controle.")
            return StartOutcome(self.state, self.last_message, errors=["vast_key_missing"])

        self._transition(GpuState.STARTING, "Solicitando sessão de GPU...")

        # (2) Orçamento
        volume_record = await self._resolve_volume(volume_id)
        if volume_record is not None:
            req.volume_machine_id = volume_record.machine_id

        plan = await self.plan_provision(req, volume_id=volume_id, estimated_hours=hours)
        if not plan.get("feasible"):
            if plan.get("volume_unavailable_hint"):
                self._transition(
                    GpuState.VOLUME_UNAVAILABLE,
                    "Não há oferta compatível no host físico do volume registrado. "
                    "Dados preservados; tente novamente mais tarde ou revise o volume.",
                )
                return StartOutcome(self.state, self.last_message, selection=plan.get("_selection"), errors=["volume_unavailable"])
            self._transition(
                GpuState.HOST_UNAVAILABLE,
                "Nenhuma oferta compatível encontrada agora. Tente novamente mais tarde.",
            )
            return StartOutcome(self.state, self.last_message, errors=["no_compatible_offers"])

        best_offer = plan["_offer_obj"]
        best_offer_id = best_offer.id
        estimate = plan["cost_estimate"]

        decision: StartDecision = await self.cost.can_start(estimate["total_usd"])
        if not decision.allowed:
            self._transition(
                GpuState.BUDGET_LIMIT_REACHED,
                "Início bloqueado pelo controle financeiro: " + " ".join(decision.reasons),
            )
            return StartOutcome(self.state, self.last_message, errors=["budget_exceeded"])

        # (3) Fila: Fase 1 sempre vazia; reserva feita antes de criar contrato.
        await self.cost.reserve(estimate["total_usd"])

        # (4) Criação da instância (idempotente)
        self._transition(GpuState.PROVISIONING, f"Criando instância a partir da oferta {best_offer_id}...")
        create_request = CreateInstanceRequest(
            offer_id=best_offer_id,
            disk_gb=max(req.min_disk_gb, 20.0),
            label=self.session.label,
            target_state="running",
            volume=(
                VolumeAttachment(
                    volume_id=volume_record.volume_id,
                    mount_path=volume_record.mount_path,
                )
                if volume_record
                else None
            ),
        )
        instance_id = await self.instances.create(create_request)
        self.session.instance_id = instance_id
        self.session.offer = best_offer
        self.session.volume_id = volume_record.volume_id if volume_record else None
        self.session.started_at = self._clock()
        self.session.reserved_usd = estimate["total_usd"]

        # (5) Poll de prontidão da instância (GPU/CUDA checados na Fase 2 pela
        # sonda do worker; aqui validamos o estado do contêiner).
        self._transition(GpuState.CHECKING, "Aguardando instância ficar 'running'...")
        try:
            instance = await self.instances.wait_for_running(
                instance_id,
                timeout_seconds=self.settings.instance_ready_timeout_seconds,
                poll_interval_seconds=self.settings.instance_poll_interval_seconds,
            )
        except VastInstanceUnrecoverableError:
            await self.cost.release(self.session.reserved_usd, instance_id)
            raise

        # (6) Afinidade real: host da instância criada deve bater com o volume.
        if volume_record is not None:
            instance_machine = instance.machine_id
            if instance_machine is not None and instance_machine != volume_record.machine_id:
                await self.cost.release(self.session.reserved_usd, instance_id)
                raise VastVolumeHostMismatchError(
                    f"Instância {instance_id} subiu no host {instance_machine}, mas o volume "
                    f"{volume_record.volume_id} pertence ao host {volume_record.machine_id}. "
                    "Sessão não validada.",
                )
            await self.registry.mark_state(volume_record.volume_id, VolumeState.IN_USE)

        # (7) Validação do worker — obrigatória para READY (§6 passo 13).
        if self.worker_probe is None:
            self.last_message = (
                f"Instância {instance_id} 'running'; worker de inferência ainda não "
                "validado (Fase 2). Estado permanece CHECKING."
            )
            return StartOutcome(
                state=self.state,
                message=self.last_message,
                session=self.session,
            )

        probe = self.worker_probe(instance, self.session.offer)
        if asyncio.iscoroutine(probe):
            probe = await probe
        if not probe.ok:
            self._fail(
                GpuState.ERROR,
                f"Worker não validado: {probe.message}",
            )
            return StartOutcome(self.state, self.last_message, session=self.session, errors=["worker_validation_failed"])

        self._transition(GpuState.READY, "GPU pronta e worker validado.")
        return StartOutcome(self.state, self.last_message, session=self.session)

    # ------------------------------------------------------------------
    # Encerramento
    # ------------------------------------------------------------------
    async def stop(
        self,
        *,
        mode: str = "stop",  # "stop" | "destroy"
        data_persisted_confirmed: bool = False,
    ) -> dict[str, Any]:
        """Encerra a sessão com procedimento seguro.

        mode="stop":    instância passa a stopped (sem custo de GPU; disco continua).
        mode="destroy": destrói a instância — exige confirmação de que os dados
                        importantes estão no volume persistente (§7).
        Nunca apaga o volume.
        """
        async with self._lock:
            if self.state == GpuState.OFFLINE:
                return {"state": self.state.value, "message": "Sessão já inativa."}
            if self._queue_size > 0:
                return {
                    "state": self.state.value,
                    "message": "Encerramento recusado: há tarefas na fila.",
                    "errors": ["queue_not_empty"],
                }

            self._transition(GpuState.STOPPING, "Encerrando sessão de GPU...")
            errors: list[str] = []
            instance_id = self.session.instance_id

            if instance_id is not None:
                if mode == "destroy":
                    if not data_persisted_confirmed:
                        self._transition(GpuState.ERROR, "Destruir exige confirmação de persistência dos dados.")
                        return {"state": self.state.value, "message": self.last_message, "errors": ["persistence_not_confirmed"]}
                    try:
                        await self.instances.destroy(instance_id, data_persisted_confirmed=True)
                    except VastInstanceNotFoundError:
                        errors.append("instance_already_gone")
                    except VastError as exc:
                        self._fail(GpuState.ERROR, f"Falha ao destruir instância: {exc.message}")
                        return {"state": self.state.value, "message": self.last_message, "errors": [exc.code]}
                else:
                    try:
                        await self.instances.set_state(instance_id, "stopped")
                    except VastInstanceNotFoundError:
                        errors.append("instance_already_gone")
                    except VastError as exc:
                        self._fail(GpuState.ERROR, f"Falha ao parar instância: {exc.message}")
                        return {"state": self.state.value, "message": self.last_message, "errors": [exc.code]}

            if self.session.volume_id is not None:
                await self.registry.mark_state(self.session.volume_id, VolumeState.AVAILABLE)

            # Custo real: se soubermos o acúmulo, liquidamos a reserva.
            if self.session.reserved_usd > 0:
                await self.cost.settle(
                    self.session.accrual_usd(),
                    instance_id,
                    note="liquidação da reserva ao encerrar sessão",
                )

            self.session = GpuSession()
            self._transition(GpuState.OFFLINE, "Sessão encerrada; dados preservados no volume.")
            result = {"state": self.state.value, "message": self.last_message, "mode": mode}
            if errors:
                result["errors"] = errors
            return result

    async def recover(self) -> dict[str, Any]:
        """Recuperação de sessão: reconsulta instância ativa na Vast.ai."""
        self._transition(GpuState.RECOVERING, "Consultando sessões ativas na Vast.ai...")
        active = await self.instances.list(status="running")
        if not active:
            self._transition(GpuState.OFFLINE, "Nenhuma instância ativa encontrada.")
            return {"state": self.state.value, "message": self.last_message, "recovered": False}
        instance = active[0]
        self.session.instance_id = instance.id
        self.session.started_at = instance.start_date or self._clock()
        self.last_message = f"Sessão recuperada da instância {instance.id}."
        return {
            "state": self.state.value,
            "message": self.last_message,
            "recovered": True,
            "instance_id": instance.id,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _default_requirements(self) -> HardwareRequirements:
        s = self.settings
        return HardwareRequirements(
            allowed_gpus=s.gpu_pref_allowed_gpus,
            min_vram_mb=s.gpu_pref_min_vram_mb,
            min_cpu_ram_mb=s.gpu_pref_min_ram_mb,
            min_disk_gb=s.gpu_pref_min_disk_gb,
            min_reliability=s.gpu_pref_min_reliability,
            min_compute_cap=s.gpu_pref_min_compute_cap,
            min_cuda_version=s.gpu_pref_cuda_min,
            max_dph_total=s.gpu_pref_max_dph_total,
        )

    async def _resolve_volume(self, volume_id: int | None) -> VolumeRecord | None:
        """Localiza registro do volume (requisitos do §5)."""
        if volume_id is None:
            records = [r for r in await self.registry.list() if r.state in (VolumeState.AVAILABLE, VolumeState.IN_USE)]
            return records[0] if records else None
        return await self.registry.get(volume_id)

    def _fail(self, state: GpuState, message: str) -> None:
        try:
            self._transition(state, message)
        except RuntimeError:
            # Transição inválida a partir do estado atual (ex.: erro duplo):
            # mantém coerência registrando em ERROR quando possível.
            logger.error("Falha durante transição: %s", message)
            self.last_message = message
