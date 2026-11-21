"""Testes dos serviços de ofertas, instâncias, volumes e billing."""

from __future__ import annotations

import httpx
import pytest
import respx

from providers.vast import (
    CreateInstanceRequest,
    HardwareRequirements,
    MutationGate,
    VastError,
    VastInstanceUnrecoverableError,
    VastOffersService,
    VastVolumesService,
    VolumeAttachment,
)
from providers.vast.vast_billing import VastBillingService
from providers.vast.vast_client import VastClientConfig, VastHttpClient
from providers.vast.vast_instances import VastInstancesService
from tests.conftest import make_offer, make_volume

BASE = "https://console.vast.ai"


def make_http(sleeps: list | None = None) -> VastHttpClient:
    config = VastClientConfig(api_key="k", backoff_base_seconds=0.001)

    async def fake_sleep(seconds: float) -> None:
        if sleeps is not None:
            sleeps.append(seconds)

    return VastHttpClient(config, sleep=fake_sleep)


# ---------------------------------------------------------------------------
# Ofertas
# ---------------------------------------------------------------------------


@respx.mock
async def test_offers_search_body_includes_filters():
    http = make_http()
    respx.post(f"{BASE}/api/v0/bundles/").mock(
        return_value=httpx.Response(200, json={"offers": [make_offer().model_dump()]})
    )
    service = VastOffersService(http)
    req = HardwareRequirements(
        allowed_gpus=["RTX 4090"],
        min_vram_mb=24576,
        min_cpu_ram_mb=32768,
        min_disk_gb=60,
        min_reliability=0.98,
        min_cuda_version=11.8,
        volume_machine_id=555,
        max_dph_total=1.0,
    )
    offers = await service.search(req)
    body = respx.calls.last.request.content.decode()
    assert '"gpu_name":{"in":["RTX 4090"]}' in body
    assert '"gpu_ram":{"gte":24576}' in body  # gpu_ram em MB (API REST)
    assert '"machine_id":{"eq":555}' in body  # afinidade de host do volume
    assert '"cuda_max_good":{"gte":11.8}' in body
    assert '"reliability":{"gte":0.98}' in body
    assert '"dph_total":{"lte":1.0}' in body
    assert '"type":"on-demand"' in body
    assert offers[0].id == 101
    await http.aclose()


@respx.mock
async def test_offers_unexpected_response_raises():
    http = make_http()
    respx.post(f"{BASE}/api/v0/bundles/").mock(return_value=httpx.Response(200, json={"foo": 1}))
    service = VastOffersService(http)
    with pytest.raises(VastError):
        await service.search(HardwareRequirements())
    await http.aclose()


# ---------------------------------------------------------------------------
# Instâncias
# ---------------------------------------------------------------------------


@respx.mock
async def test_instance_create_blocked_by_gate():
    http = make_http()
    service = VastInstancesService(http, MutationGate(enabled=False))
    with pytest.raises(VastError) as excinfo:
        await service.create(CreateInstanceRequest(offer_id=1))
    assert excinfo.value.code == "vast_mutations_disabled"
    await http.aclose()


@respx.mock
async def test_instance_create_payload_and_contract():
    http = make_http()
    route = respx.put(f"{BASE}/api/v0/asks/101/").mock(
        return_value=httpx.Response(200, json={"success": True, "new_contract": 90001})
    )
    service = VastInstancesService(http, MutationGate(enabled=True))
    request = CreateInstanceRequest(
        offer_id=101,
        disk_gb=25,
        label="lv",
        volume=VolumeAttachment(volume_id=42, mount_path="/data"),
    )
    contract = await service.create(request)
    assert contract == 90001
    body = route.calls.last.request.content.decode()
    assert '"client_id":"me"' in body
    assert '"image":"vastai/pytorch:@vastai-automatic-tag"' in body
    assert '"volume_info":{"mount_path":"/data","create_new":false,"volume_id":42}' in body
    assert '"disk":25' in body
    await http.aclose()


@respx.mock
async def test_instance_create_failure_raises():
    http = make_http()
    respx.put(f"{BASE}/api/v0/asks/101/").mock(
        return_value=httpx.Response(400, json={"success": False, "error": "invalid_args", "msg": "bad"})
    )
    service = VastInstancesService(http, MutationGate(enabled=True))
    with pytest.raises(VastError):
        await service.create(CreateInstanceRequest(offer_id=101))
    await http.aclose()


@respx.mock
async def test_wait_for_running_poll_trap():
    http = make_http()
    statuses = iter(["loading", "exited"])
    respx.get(f"{BASE}/api/v0/instances/9/").mock(
        side_effect=lambda request: httpx.Response(
            200,
            json={"id": 9, "actual_status": next(statuses), "machine_id": 555},
        )
    )
    service = VastInstancesService(http, MutationGate(enabled=True), sleep=_no_sleep())
    with pytest.raises(VastInstanceUnrecoverableError):
        await service.wait_for_running(9, timeout_seconds=10, poll_interval_seconds=0.001)
    await http.aclose()


@respx.mock
async def test_wait_for_running_timeout():
    http = make_http()
    respx.get(f"{BASE}/api/v0/instances/9/").mock(
        return_value=httpx.Response(200, json={"id": 9, "actual_status": "loading", "machine_id": 555})
    )
    service = VastInstancesService(http, MutationGate(enabled=True), sleep=_no_sleep())
    with pytest.raises(VastError) as excinfo:
        await service.wait_for_running(9, timeout_seconds=0.05, poll_interval_seconds=0.01)
    assert excinfo.value.code == "vast_instance_ready_timeout"
    await http.aclose()


@respx.mock
async def test_wait_for_running_success():
    http = make_http()
    statuses = iter(["loading", "running"])
    respx.get(f"{BASE}/api/v0/instances/9/").mock(
        side_effect=lambda request: httpx.Response(
            200, json={"id": 9, "actual_status": next(statuses), "machine_id": 555}
        )
    )
    service = VastInstancesService(http, MutationGate(enabled=True), sleep=_no_sleep())
    instance = await service.wait_for_running(9, timeout_seconds=10, poll_interval_seconds=0.001)
    assert instance.actual_status == "running"
    await http.aclose()


@respx.mock
async def test_destroy_requires_persistence_confirmation():
    http = make_http()
    route = respx.delete(f"{BASE}/api/v0/instances/5/").mock(
        return_value=httpx.Response(200, json={"success": True})
    )
    service = VastInstancesService(http, MutationGate(enabled=True))
    with pytest.raises(VastError) as excinfo:
        await service.destroy(5, data_persisted_confirmed=False)
    assert excinfo.value.code == "vast_destroy_blocked"
    assert not route.called
    await service.destroy(5, data_persisted_confirmed=True)
    assert route.called
    await http.aclose()


@respx.mock
async def test_list_instances_pagination():
    http = make_http()
    pages = [
        httpx.Response(
            200,
            json={
                "success": True,
                "instances": [{"id": 1, "actual_status": "running"}],
                "next_token": "tok1",
            },
        ),
        httpx.Response(
            200,
            json={"success": True, "instances": [{"id": 2, "actual_status": "stopped"}], "next_token": None},
        ),
    ]
    respx.get(f"{BASE}/api/v1/instances/").mock(side_effect=pages)
    service = VastInstancesService(http, MutationGate(enabled=True))
    instances = await service.list()
    assert [i.id for i in instances] == [1, 2]
    await http.aclose()


# ---------------------------------------------------------------------------
# Volumes
# ---------------------------------------------------------------------------


@respx.mock
async def test_volume_host_affinity_mismatch():
    http = make_http()
    service = VastVolumesService(http, MutationGate(enabled=True))
    volume = make_volume(machine_id=111)
    offer = make_offer(machine_id=555)
    from providers.vast import VastVolumeHostMismatchError

    with pytest.raises(VastVolumeHostMismatchError):
        service.validate_host_affinity(volume, offer)
    await http.aclose()


@respx.mock
async def test_volume_host_affinity_match():
    http = make_http()
    service = VastVolumesService(http, MutationGate(enabled=True))
    volume = make_volume(machine_id=555)
    offer = make_offer(machine_id=555)
    service.validate_host_affinity(volume, offer)  # não levanta
    await http.aclose()


@respx.mock
async def test_volume_rent_gated():
    http = make_http()
    service = VastVolumesService(http, MutationGate(enabled=False))
    with pytest.raises(VastError):
        await service.rent(offer_id=333, size_gb=100)
    await http.aclose()


@respx.mock
async def test_volume_rent_payload():
    http = make_http()
    route = respx.put(f"{BASE}/api/v0/volumes/").mock(
        return_value=httpx.Response(200, json={"success": True, "volume_name": "V.20118481"})
    )
    service = VastVolumesService(http, MutationGate(enabled=True))
    name = await service.rent(offer_id=420, size_gb=100)
    assert name == "V.20118481"
    body = route.calls.last.request.content.decode()
    assert '"id":420' in body and '"size":100' in body
    await http.aclose()


@respx.mock
async def test_volume_list_mapping():
    http = make_http()
    respx.get(f"{BASE}/api/v0/volumes/").mock(
        return_value=httpx.Response(
            200,
            json={"volumes": [{"id": 42, "machine_id": 555, "disk_space": 100.0, "storage_total_cost": 12.0}]},
        )
    )
    service = VastVolumesService(http, MutationGate(enabled=True))
    volumes = await service.list()
    assert volumes[0].machine_id == 555
    await http.aclose()


def test_volume_adapter_never_deletes():
    """Regra §5: o adaptador não expõe exclusão de volumes."""
    public_methods = [m for m in dir(VastVolumesService) if not m.startswith("_")]
    assert all("delete" not in m and "destroy" not in m for m in public_methods)


# ---------------------------------------------------------------------------
# Billing
# ---------------------------------------------------------------------------


@respx.mock
async def test_billing_monthly_usage_pagination_and_aggregation():
    http = make_http()
    responses = [
        httpx.Response(
            200,
            json={
                "success": True,
                "count": 2,
                "total": 3,
                "next_token": "t2",
                "results": [
                    {"type": "instance", "source": "instance-1", "amount": 3.5, "start": 1, "end": 2},
                    {"type": "volume", "source": "volume-2", "amount": 1.0, "start": 1, "end": 2},
                ],
            },
        ),
        httpx.Response(
            200,
            json={
                "success": True,
                "count": 1,
                "total": 3,
                "next_token": None,
                "results": [
                    {"type": "instance", "source": "instance-3", "amount": 0.5, "start": 2, "end": 3},
                ],
            },
        ),
    ]
    respx.get(f"{BASE}/api/v0/charges/").mock(side_effect=responses)
    service = VastBillingService(http)
    usage = await service.monthly_usage(period_start_unix=1, period_end_unix=100)
    assert usage.instance_charges_usd == pytest.approx(4.0)
    assert usage.volume_charges_usd == pytest.approx(1.0)
    assert usage.total_usd == pytest.approx(5.0)
    assert len(usage.entries) == 3
    await http.aclose()


@respx.mock
async def test_billing_charges_filter_payload():
    http = make_http()
    respx.get(f"{BASE}/api/v0/charges/").mock(
        return_value=httpx.Response(200, json={"success": True, "results": []})
    )
    service = VastBillingService(http)
    await service.list_charges(day_start_unix=100, day_end_unix=200, contract_types=["instance"])
    url = respx.calls.last.request.url
    assert "select_filters=" in str(url)
    await http.aclose()


def _no_sleep():
    async def fake_sleep(seconds: float) -> None:
        pass

    return fake_sleep
