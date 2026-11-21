"""Testes do seletor de ofertas (critérios do §4)."""

from __future__ import annotations

from app.services.offer_selector import (
    R_CUDA,
    R_DATA_MISSING,
    R_DISK,
    R_GPU_MODEL,
    R_HOST_VOLUME,
    R_NOT_RENTABLE,
    R_PRICE,
    R_RAM,
    R_RELIABILITY,
    R_VM,
    R_VRAM,
    filter_offers,
)
from providers.vast.vast_schemas import HardwareRequirements
from tests.conftest import make_offer


def base_req(**overrides) -> HardwareRequirements:
    defaults = dict(
        allowed_gpus=["RTX 4090"],
        min_vram_mb=24576,
        min_cpu_ram_mb=32768,
        min_cpu_cores=4,
        min_disk_gb=60,
        min_reliability=0.98,
        min_compute_cap=8.0,
        min_cuda_version=11.8,
    )
    defaults.update(overrides)
    return HardwareRequirements(**defaults)


def test_offer_with_insufficient_vram_rejected():
    offers = [make_offer(id=1, gpu_ram=8192), make_offer(id=2, gpu_ram=24576)]
    result = filter_offers(offers, base_req())
    assert result.best.id == 2
    assert (1, R_VRAM) in result.rejected


def test_offer_without_cuda_compatibility_rejected():
    offers = [make_offer(id=1, cuda_max_good=11.0), make_offer(id=2, cuda_max_good=12.4)]
    result = filter_offers(offers, base_req(min_cuda_version=11.8))
    assert (1, R_CUDA) in result.rejected
    assert result.best.id == 2


def test_offer_low_reliability_rejected():
    offers = [make_offer(id=1, reliability=0.90)]
    result = filter_offers(offers, base_req())
    assert (1, R_RELIABILITY) in result.rejected
    assert result.best is None


def test_offer_insufficient_ram_rejected():
    offers = [make_offer(id=1, cpu_ram=16384)]
    result = filter_offers(offers, base_req())
    assert (1, R_RAM) in result.rejected


def test_offer_insufficient_disk_rejected():
    offers = [make_offer(id=1, disk_space=30.0)]
    result = filter_offers(offers, base_req())
    assert (1, R_DISK) in result.rejected


def test_offer_on_wrong_host_for_volume_rejected():
    offers = [make_offer(id=1, machine_id=999), make_offer(id=2, machine_id=555)]
    req = base_req(volume_machine_id=555)
    result = filter_offers(offers, req)
    assert (1, R_HOST_VOLUME) in result.rejected
    assert result.best.id == 2


def test_offer_not_rentable_rejected():
    offers = [make_offer(id=1, rentable=False)]
    result = filter_offers(offers, base_req())
    assert (1, R_NOT_RENTABLE) in result.rejected


def test_offer_vm_excluded():
    offers = [make_offer(id=1, vms_enabled=True)]
    result = filter_offers(offers, base_req())
    assert (1, R_VM) in result.rejected


def test_offer_gpu_not_allowed_rejected():
    offers = [make_offer(id=1, gpu_name="RTX 2060")]
    result = filter_offers(offers, base_req())
    assert (1, R_GPU_MODEL) in result.rejected


def test_offer_over_price_cap_rejected():
    offers = [make_offer(id=1, dph_total=5.0)]
    result = filter_offers(offers, base_req(max_dph_total=1.0))
    assert (1, R_PRICE) in result.rejected


def test_incomplete_data_rejected():
    offers = [make_offer(id=1, gpu_ram=None)]
    result = filter_offers(offers, base_req())
    assert (1, R_DATA_MISSING) in result.rejected


def test_cheapest_compatible_offer_wins():
    offers = [
        make_offer(id=1, dph_total=0.60),
        make_offer(id=2, dph_total=0.35),
        make_offer(id=3, dph_total=0.50, reliability=0.999),
    ]
    result = filter_offers(offers, base_req())
    assert result.best.id == 2


def test_compute_cap_filter():
    offers = [make_offer(id=1, compute_cap=7.5)]
    result = filter_offers(offers, base_req(min_compute_cap=8.0))
    assert result.best is None


def test_selection_summary_counts_reasons():
    offers = [
        make_offer(id=1, gpu_ram=8192),
        make_offer(id=2, gpu_ram=8192),
        make_offer(id=3, gpu_ram=24576),
    ]
    result = filter_offers(offers, base_req())
    assert result.rejection_summary[R_VRAM] == 2
    assert result.considered == 3
