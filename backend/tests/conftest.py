"""Fixtures compartilhadas dos testes.

Todos os testes usam mocks/respx — NENHUM teste desta suíte contata a
Vast.ai real ou gera cobrança (§12/§14 do adendo: ambiente simulado).
"""

from __future__ import annotations

from typing import Any

from app.config import Settings
from app.services.gpu_manager import GpuManager, WorkerProbeResult
from app.services.storage_registry import StorageRegistry, VolumeRecord, VolumeState
from providers.vast import (
    CreateInstanceRequest,
    HardwareRequirements,
    RentalType,
    VastBillingService,
    VastOffer,
    VastVolume,
)
from providers.vast.vast_exceptions import (
    VastError,
    VastInstanceUnrecoverableError,
)


def make_settings(tmp_path, **overrides: Any) -> Settings:
    defaults = dict(
        localvideo_api_key="dev-client-key",
        localvideo_admin_api_key="dev-admin-key",
        vast_api_key="test-vast-key",
        vast_enable_mutations=True,
        data_dir=str(tmp_path / "data"),
        rate_limit_requests_per_minute=100_000,
        rate_limit_burst=1_000,
        instance_poll_interval_seconds=0.01,
        instance_ready_timeout_seconds=5.0,
        vast_retry_attempts=3,
        vast_backoff_base_seconds=0.001,
        estimated_session_hours=1.0,
        gpu_monthly_budget_brl=100.0,
    )
    defaults.update(overrides)
    return Settings(**defaults)


def make_offer(**overrides: Any) -> VastOffer:
    base = dict(
        id=101,
        machine_id=555,
        host_id=7,
        gpu_name="RTX 4090",
        num_gpus=1,
        gpu_ram=24576,
        gpu_total_ram=24576,
        cpu_name="Ryzen 9",
        cpu_cores=16,
        cpu_ram=65536,
        disk_space=500.0,
        disk_bw=1200.0,
        dph_total=0.40,
        reliability=0.999,
        compute_cap=8.9,
        cuda_max_good=12.4,
        rentable=True,
        rented=False,
        verification="verified",
        vms_enabled=False,
        inet_down=1500.0,
        inet_up=900.0,
        storage_cost=0.15,
        dlperf_per_dphtotal=35.0,
        avail_vol_ask_id=333333,
    )
    base.update(overrides)
    return VastOffer.model_validate(base)


def make_volume(**overrides: Any) -> VastVolume:
    base = dict(
        id=42,
        machine_id=555,
        host_id=7,
        disk_space=100.0,
        storage_total_cost=12.0,
        status="active",
        verification="verified",
    )
    base.update(overrides)
    return VastVolume.model_validate(base)


# ---------------------------------------------------------------------------
# Fakes de serviço (mesma interface dos serviços Vast, sem rede)
# ---------------------------------------------------------------------------


class FakeOffersService:
    def __init__(self, offers: list[VastOffer] | None = None, error: VastError | None = None) -> None:
        self.offers = offers or []
        self.error = error
        self.calls: list[HardwareRequirements] = []

    async def search(self, requirements: HardwareRequirements, rental_type=RentalType.ON_DEMAND, allocated_storage_gb: float = 20.0):
        self.calls.append(requirements)
        if self.error is not None:
            raise self.error
        return self.offers


class FakeInstancesService:
    def __init__(
        self,
        *,
        statuses: list[str] | None = None,
        create_error: VastError | None = None,
        machine_id_of_instance: int = 555,
    ) -> None:
        self.created: list[CreateInstanceRequest] = []
        self.create_error = create_error
        self.statuses = list(statuses or ["running"])
        self.stopped: list[int] = []
        self.destroyed: list[int] = []
        self.machine_id_of_instance = machine_id_of_instance
        self.list_has_instance = True

    async def create(self, request: CreateInstanceRequest) -> int:
        if self.create_error is not None:
            raise self.create_error
        self.created.append(request)
        return 90001

    async def get(self, instance_id: int):
        from providers.vast import VastInstance

        status = self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
        return VastInstance.model_validate(
            {
                "id": instance_id,
                "actual_status": status,
                "machine_id": self.machine_id_of_instance,
                "dph_total": 0.40,
                "gpu_name": "RTX 4090",
            }
        )

    async def list(self, **kwargs):
        from providers.vast import VastInstance

        if not self.list_has_instance:
            return []
        return [
            VastInstance.model_validate(
                {
                    "id": 90001,
                    "actual_status": "running",
                    "machine_id": self.machine_id_of_instance,
                    "start_date": 1700000000.0,
                }
            )
        ]

    async def set_state(self, instance_id: int, state: str) -> None:
        self.stopped.append(instance_id)

    async def destroy(self, instance_id: int, *, data_persisted_confirmed: bool) -> None:
        if not data_persisted_confirmed:
            raise VastError("bloqueado", code="vast_destroy_blocked")
        self.destroyed.append(instance_id)

    async def wait_for_running(self, instance_id: int, *, timeout_seconds: float = 900.0, poll_interval_seconds: float = 0.01, on_poll=None):
        from providers.vast import VastInstance

        for status in self.statuses:
            if status == "running":
                return VastInstance.model_validate(
                    {"id": instance_id, "actual_status": "running", "machine_id": self.machine_id_of_instance}
                )
            if status in ("exited", "unknown", "offline"):
                raise VastInstanceUnrecoverableError(f"poll-trap: {status}")
        return VastInstance.model_validate(
            {"id": instance_id, "actual_status": "running", "machine_id": self.machine_id_of_instance}
        )


class FakeVolumesService:
    def __init__(self, volumes: list[VastVolume] | None = None) -> None:
        self.volumes = volumes or []

    async def list(self, *, volume_type: str = "all"):
        return self.volumes

    async def get(self, volume_id: int):
        for volume in self.volumes:
            if volume.id == volume_id:
                return volume
        return None

    async def rent(self, offer_id: int, size_gb: int) -> str:
        return f"V.{offer_id}"


class FakeBillingService(VastBillingService):
    def __init__(self) -> None:
        pass  # não chama super: fake sem HTTP


def build_gpu_manager(settings, offers=None, instances=None, volumes=None, billing=None, worker_probe=None, cost_manager=None, storage_registry=None) -> GpuManager:
    cost = cost_manager or build_cost_manager(settings)
    registry = storage_registry or StorageRegistry(data_dir=settings.data_dir)
    return GpuManager(
        settings=settings,
        http=None,
        offers=offers or FakeOffersService([make_offer()]),
        instances=instances or FakeInstancesService(),
        volumes=volumes or FakeVolumesService(),
        billing=billing or FakeBillingService(),
        cost_manager=cost,
        storage_registry=registry,
        worker_probe=worker_probe,
    )


def build_cost_manager(settings):
    from app.services.cost_manager import CostManager

    return CostManager(
        data_dir=settings.data_dir,
        monthly_budget_brl=settings.gpu_monthly_budget_brl,
        usd_to_brl_rate=settings.usd_to_brl_rate,
        alert_threshold=settings.budget_alert_threshold,
        block_threshold=settings.budget_block_threshold,
        storage_reserve_brl=settings.storage_reserve_brl,
    )


async def add_volume_record(registry: StorageRegistry, volume: VastVolume) -> None:
    await registry.upsert(
        VolumeRecord(
            volume_id=volume.id,
            machine_id=volume.machine_id,
            capacity_gb=volume.disk_space or 0.0,
            mount_path="/data",
            state=VolumeState.AVAILABLE,
        )
    )


def ok_probe(instance=None, offer=None) -> WorkerProbeResult:
    return WorkerProbeResult(ok=True, message="worker validado")


def failing_probe(instance=None, offer=None) -> WorkerProbeResult:
    return WorkerProbeResult(ok=False, message="worker falhou na validação")
