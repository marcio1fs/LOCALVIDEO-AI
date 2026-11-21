"""Testes do GPU Manager: máquina de estados, pipeline, concorrência, orçamento.

Todos usam fakes de serviço — nenhum contato real com a Vast.ai e nenhuma
cobrança (ambiente simulado, §12).
"""

from __future__ import annotations

import asyncio

import pytest

from app.config import Settings
from app.services.gpu_manager import GpuState
from app.services.storage_registry import StorageRegistry, VolumeState
from providers.vast import (
    VastOfferUnavailableError,
)
from tests.conftest import (
    FakeBillingService,
    FakeInstancesService,
    FakeOffersService,
    FakeVolumesService,
    add_volume_record,
    build_cost_manager,
    build_gpu_manager,
    failing_probe,
    make_offer,
    make_settings,
    make_volume,
    ok_probe,
)


@pytest.fixture
def settings(tmp_path) -> Settings:
    return make_settings(tmp_path)


def _manager(settings, offers=None, instances=None, volumes=None, worker_probe=None, billing=None):
    offers = offers if offers is not None else FakeOffersService([make_offer()])
    instances = instances if instances is not None else FakeInstancesService()
    volumes = volumes if volumes is not None else FakeVolumesService()
    return build_gpu_manager(
        settings,
        offers=offers,
        instances=instances,
        volumes=volumes,
        billing=billing or FakeBillingService(),
        worker_probe=worker_probe,
    )


async def test_initial_status_offline(settings):
    manager = _manager(settings)
    status = await manager.status()
    assert status["state"] == "OFFLINE"
    assert status["provider"] == "vast.ai"


async def test_invalid_state_transition_raises(settings):
    manager = _manager(settings)
    with pytest.raises(RuntimeError):
        manager._transition(GpuState.READY, "salto ilegal")


async def test_plan_provision_returns_best_offer(settings):
    manager = _manager(settings)
    plan = await manager.plan_provision()
    assert plan["feasible"] is True
    assert plan["offer"]["offer_id"] == 101
    assert plan["cost_estimate"]["gpu_hourly_usd"] == 0.40
    assert plan["cost_estimate"]["is_estimate"] is True


async def test_plan_without_compatible_offers_is_not_feasible(settings):
    manager = _manager(settings, offers=FakeOffersService([make_offer(id=1, gpu_ram=8192)]))
    plan = await manager.plan_provision()
    assert plan["feasible"] is False
    assert plan["rejection_summary"].get("VRAM_INSUFICIENTE") == 1


async def test_start_without_worker_probe_stays_checking(settings):
    """§6 passo 13: sem validação real do worker, nunca declara READY."""
    manager = _manager(settings, worker_probe=None)
    outcome = await manager.start()
    assert outcome.state is GpuState.CHECKING
    assert outcome.session.instance_id == 90001
    assert "worker" in outcome.message.lower()


async def test_start_with_valid_worker_reaches_ready(settings):
    manager = _manager(settings, worker_probe=ok_probe)
    outcome = await manager.start()
    assert outcome.state is GpuState.READY
    assert outcome.session.instance_id == 90001


async def test_start_with_failing_worker_goes_error(settings):
    manager = _manager(settings, worker_probe=failing_probe)
    outcome = await manager.start()
    assert outcome.state is GpuState.ERROR
    assert "worker_validation_failed" in outcome.errors


async def test_simultaneous_starts_only_one_provisions(settings):
    """§12: duas solicitações simultâneas -> uma única criação de instância."""
    instances = FakeInstancesService()
    manager = _manager(settings, instances=instances, worker_probe=ok_probe)

    async def do_start():
        return await manager.start()

    outcomes = await asyncio.gather(do_start(), do_start())
    # Apenas uma instância criada; a outra solicitação foi recusada.
    assert len(instances.created) == 1
    with_instance = {o.session.instance_id for o in outcomes if o.session is not None}
    assert 90001 in with_instance
    refused = [o for o in outcomes if o.errors and o.errors[0] in ("gpu_busy", "session_already_active")]
    assert len(refused) >= 1
    assert manager.state in (GpuState.READY, GpuState.CHECKING)


async def test_budget_exceeded_blocks_start(settings):
    cost = build_cost_manager(settings)
    await cost.reserve(20.0)  # consome 100% do orçamento (100 BRL / 5.0)
    registry = StorageRegistry(data_dir=settings.data_dir)
    manager = build_gpu_manager(
        settings,
        offers=FakeOffersService([make_offer()]),
        instances=FakeInstancesService(),
        volumes=FakeVolumesService(),
        billing=FakeBillingService(),
        cost_manager=cost,
        storage_registry=registry,
        worker_probe=ok_probe,
    )
    outcome = await manager.start()
    assert outcome.state is GpuState.BUDGET_LIMIT_REACHED
    assert "budget_exceeded" in outcome.errors


async def test_no_compatible_offer_goes_host_unavailable(settings):
    manager = _manager(settings, offers=FakeOffersService([make_offer(id=1, gpu_ram=8192)]), worker_probe=ok_probe)
    outcome = await manager.start()
    assert outcome.state is GpuState.HOST_UNAVAILABLE
    assert "no_compatible_offers" in outcome.errors


async def test_volume_of_different_host_goes_volume_unavailable(settings):
    """§4/§5: oferta existe, mas não no host do volume registrado."""
    registry = StorageRegistry(data_dir=settings.data_dir)
    await add_volume_record(registry, make_volume(id=42, machine_id=999))  # host 999
    manager = build_gpu_manager(
        settings,
        offers=FakeOffersService([make_offer(machine_id=555)]),  # só host 555
        instances=FakeInstancesService(),
        volumes=FakeVolumesService(),
        billing=FakeBillingService(),
        cost_manager=build_cost_manager(settings),
        storage_registry=registry,
        worker_probe=ok_probe,
    )
    outcome = await manager.start(volume_id=42)
    assert outcome.state is GpuState.VOLUME_UNAVAILABLE
    assert "volume_unavailable" in outcome.errors


async def test_volume_is_attached_and_host_validated(settings):
    registry = StorageRegistry(data_dir=settings.data_dir)
    await add_volume_record(registry, make_volume(id=42, machine_id=555))
    instances = FakeInstancesService(machine_id_of_instance=555)
    manager = build_gpu_manager(
        settings,
        offers=FakeOffersService([make_offer(machine_id=555)]),
        instances=instances,
        volumes=FakeVolumesService(),
        billing=FakeBillingService(),
        cost_manager=build_cost_manager(settings),
        storage_registry=registry,
        worker_probe=ok_probe,
    )
    outcome = await manager.start(volume_id=42)
    assert outcome.state is GpuState.READY
    assert instances.created[0].volume is not None
    assert instances.created[0].volume.volume_id == 42
    record = await registry.get(42)
    assert record.state is VolumeState.IN_USE


async def test_instance_host_mismatch_after_create_raises(settings):
    """Instância subiu em host diferente do volume -> VOLUME_UNAVAILABLE."""
    registry = StorageRegistry(data_dir=settings.data_dir)
    await add_volume_record(registry, make_volume(id=42, machine_id=999))
    instances = FakeInstancesService(machine_id_of_instance=555)  # host diferente!
    manager = build_gpu_manager(
        settings,
        offers=FakeOffersService([make_offer(machine_id=999)]),
        instances=instances,
        volumes=FakeVolumesService(),
        billing=FakeBillingService(),
        cost_manager=build_cost_manager(settings),
        storage_registry=registry,
        worker_probe=ok_probe,
    )
    outcome = await manager.start(volume_id=42)
    assert outcome.state is GpuState.VOLUME_UNAVAILABLE


async def test_instance_creation_failure_goes_error(settings):
    instances = FakeInstancesService(create_error=VastOfferUnavailableError("oferta sumiu"))
    manager = _manager(settings, instances=instances, worker_probe=ok_probe)
    outcome = await manager.start()
    assert outcome.state is GpuState.HOST_UNAVAILABLE
    assert "offer_unavailable" in outcome.errors


async def test_poll_trap_goes_error(settings):
    instances = FakeInstancesService(statuses=["exited"])
    manager = _manager(settings, instances=instances, worker_probe=ok_probe)
    outcome = await manager.start()
    assert outcome.state is GpuState.ERROR
    assert "instance_poll_trap" in outcome.errors


async def test_stop_releases_instance(settings):
    manager = _manager(settings, worker_probe=ok_probe)
    await manager.start()
    result = await manager.stop(mode="stop")
    assert result["state"] == "OFFLINE"
    assert manager.session.instance_id is None


async def test_destroy_requires_persistence_confirmation(settings):
    manager = _manager(settings, worker_probe=ok_probe)
    await manager.start()
    result = await manager.stop(mode="destroy", data_persisted_confirmed=False)
    assert "persistence_not_confirmed" in result.get("errors", [])


async def test_destroy_with_confirmation_destroys(settings):
    instances = FakeInstancesService()
    manager = _manager(settings, instances=instances, worker_probe=ok_probe)
    await manager.start()
    result = await manager.stop(mode="destroy", data_persisted_confirmed=True)
    assert result["state"] == "OFFLINE"
    assert instances.destroyed == [90001]


async def test_stop_refused_with_queue_nonempty(settings):
    manager = _manager(settings, worker_probe=ok_probe)
    await manager.start()
    manager._queue_size = 1
    result = await manager.stop()
    assert "queue_not_empty" in result.get("errors", [])
    manager._queue_size = 0


async def test_cost_reserved_and_settled_on_stop(settings):
    manager = _manager(settings, worker_probe=ok_probe)
    await manager.start()
    reserved = manager.session.reserved_usd
    assert reserved > 0
    await manager.stop()
    ledger = await manager.cost.ledger()
    kinds = [entry["kind"] for entry in ledger]
    assert "reservation" in kinds
    assert "settlement" in kinds


async def test_recover_finds_running_instance(settings):
    manager = _manager(settings, worker_probe=ok_probe)
    result = await manager.recover()
    assert result["recovered"] is True
    assert result["instance_id"] == 90001


async def test_recover_without_instance_goes_offline(settings):
    instances = FakeInstancesService()
    instances.list_has_instance = False  # nenhuma sessão ativa na Vast.ai
    manager = _manager(settings, instances=instances)
    result = await manager.recover()
    assert result["recovered"] is False
    assert manager.state is GpuState.OFFLINE


async def test_confirm_cost_required(settings):
    manager = _manager(settings, worker_probe=ok_probe)
    outcome = await manager.start(confirm_cost=False)
    assert outcome.session is None
    assert manager.state is GpuState.OFFLINE


async def test_status_includes_budget(settings):
    manager = _manager(settings, worker_probe=ok_probe)
    await manager.start()
    status = await manager.status()
    assert status["budget"]["budget_brl"] == settings.gpu_monthly_budget_brl
    assert status["budget"]["state"] in ("OK", "ALERT_70", "BLOCK_90", "LIMIT_REACHED")
    assert status["session"]["accrual_brl"] >= 0
