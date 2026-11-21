"""Testes do Cost Manager (regras de 70%/90% do §8)."""

from __future__ import annotations

import pytest

from app.services.cost_manager import BudgetState, CostManager
from tests.conftest import make_settings


@pytest.fixture
def cost(tmp_path) -> CostManager:
    settings = make_settings(tmp_path)
    return CostManager(
        data_dir=settings.data_dir,
        monthly_budget_brl=100.0,
        usd_to_brl_rate=5.0,
        alert_threshold=0.70,
        block_threshold=0.90,
        storage_reserve_brl=5.0,
    )


async def test_initial_state_ok(cost: CostManager):
    status = await cost.budget_status()
    assert status.state is BudgetState.OK
    assert status.remaining_brl == 100.0


async def test_alert_at_70_percent(cost: CostManager):
    # 72 BRL comprometidos = 72% -> ALERT_70
    await cost.reserve(14.4)  # 72 BRL / taxa 5.0
    status = await cost.budget_status()
    assert status.state is BudgetState.ALERT_70
    assert any("70%" in w or "Atenção" in w for w in status.warnings)


async def test_block_at_90_percent(cost: CostManager):
    await cost.reserve(18.5)  # 92.5 BRL = 92.5% -> BLOCK_90
    decision = await cost.can_start(estimated_session_usd=1.0)
    assert decision.allowed is False
    assert any("90%" in r for r in decision.reasons)


async def test_limit_reached_blocks_everything(cost: CostManager):
    await cost.reserve(20.0)  # 100 BRL
    decision = await cost.can_start(estimated_session_usd=0.1)
    assert decision.allowed is False
    status = await cost.budget_status()
    assert status.state is BudgetState.LIMIT_REACHED


async def test_estimate_above_remaining_blocks(cost: CostManager):
    # 80% consumido -> ainda sob 90%, mas estimativa de 25 BRL > saldo 20 BRL
    await cost.reserve(16.0)
    decision = await cost.can_start(estimated_session_usd=5.0)  # 25 BRL
    assert decision.allowed is False
    assert any("saldo" in r for r in decision.reasons)


async def test_storage_reserve_guard(cost: CostManager):
    # Consumo de 96 BRL deixa 4 BRL — abaixo da reserva de 5 BRL
    await cost.reserve(19.2)
    decision = await cost.can_start(estimated_session_usd=0.5)  # 2.5 BRL
    assert decision.allowed is False
    assert any("reserva mínima" in r for r in decision.reasons)


async def test_settle_consumes_reservation(cost: CostManager):
    await cost.reserve(10.0)  # 50 BRL
    await cost.settle(10.0)   # cobrança real igual à reserva
    status = await cost.budget_status()
    # settle substitui a reserva: total comprometido continua 50 BRL
    assert status.committed_brl == pytest.approx(50.0)


async def test_external_charges_generate_warning(cost: CostManager):
    warnings = await cost.record_external_charges(12.0)
    status = await cost.budget_status()
    assert status.external_brl == pytest.approx(60.0)
    assert any("externas" in w for w in warnings)


async def test_apply_external_usage_splits_excess(cost: CostManager):
    await cost.reserve(2.0)  # 10 BRL reservados
    # Cobrança real de 15 BRL: 10 BRL consomem a reserva, 5 BRL são excedente
    await cost.apply_external_usage(3.0)
    status = await cost.budget_status()
    assert status.external_brl == pytest.approx(5.0)  # 5 BRL excedente
    assert status.committed_brl == pytest.approx(15.0)


async def test_release_returns_budget(cost: CostManager):
    await cost.reserve(10.0)
    await cost.release(10.0)
    status = await cost.budget_status()
    assert status.committed_brl == pytest.approx(0.0)


async def test_estimate_session_math(cost: CostManager):
    estimate = cost.estimate_session(
        hourly_price_usd=0.40,
        hours=2.0,
        storage_monthly_usd=14.4,  # 1.2 BRL/mês equivalente
    )
    assert estimate["gpu_total_usd"] == pytest.approx(0.80)
    assert estimate["storage_total_usd"] == pytest.approx(0.0394, rel=0.01)
    assert estimate["is_estimate"] is True


async def test_ledger_persists(tmp_path):
    settings = make_settings(tmp_path)
    cost1 = CostManager(data_dir=settings.data_dir, monthly_budget_brl=100.0, usd_to_brl_rate=5.0)
    await cost1.reserve(2.0)
    cost2 = CostManager(data_dir=settings.data_dir, monthly_budget_brl=100.0, usd_to_brl_rate=5.0)
    status = await cost2.budget_status()
    assert status.committed_brl == pytest.approx(10.0)  # reserva carregada do disco
