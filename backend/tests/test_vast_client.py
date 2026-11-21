"""Testes do cliente HTTP Vast.ai: retry, backoff, idempotência, erros."""

from __future__ import annotations

import httpx
import pytest
import respx

from providers.vast.vast_client import VastClientConfig, VastHttpClient
from providers.vast.vast_exceptions import (
    VastAuthError,
    VastOfferUnavailableError,
    VastRateLimitError,
    VastSearchQuotaError,
    VastTransportError,
)


def make_client(**overrides) -> VastHttpClient:
    config_kwargs = dict(
        api_key="k",
        retry_attempts=3,
        backoff_base_seconds=0.001,
        backoff_factor=1.1,
        idempotency_ttl_seconds=300,
    )
    config_kwargs.update(overrides)
    config = VastClientConfig(**config_kwargs)
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    return VastHttpClient(config, sleep=fake_sleep), sleeps


BASE = "https://console.vast.ai"


@respx.mock
async def test_retry_on_502_then_success():
    client, sleeps = make_client()
    route = respx.put(f"{BASE}/api/v0/instances/123/").mock(
        side_effect=[
            httpx.Response(502, json={"success": False, "error": "bad_gateway"}),
            httpx.Response(200, json={"success": True}),
        ]
    )
    status, data = await client.request("PUT", "/instances/123", json_body={})
    assert status == 200
    assert data["success"] is True
    assert route.call_count == 2
    assert len(sleeps) == 1
    await client.aclose()


@respx.mock
async def test_retry_on_429_honors_retry_after():
    client, sleeps = make_client()
    respx.get(f"{BASE}/api/v0/instances/9/").mock(
        side_effect=[
            httpx.Response(429, json={"detail": "API requests too frequent"}, headers={"Retry-After": "2"}),
            httpx.Response(200, json={"success": True, "id": 9}),
        ]
    )
    status, data = await client.request("GET", "/instances/9")
    assert data["id"] == 9
    assert sleeps == [2.0]
    await client.aclose()


@respx.mock
async def test_search_quota_429_not_retried():
    client, sleeps = make_client()
    respx.post(f"{BASE}/api/v0/bundles/").mock(
        return_value=httpx.Response(429, json={"error": "search_quota_exceeded"})
    )
    with pytest.raises(VastSearchQuotaError) as excinfo:
        await client.request("POST", "/bundles/", json_body={})
    assert excinfo.value.quota_exceeded is True
    assert sleeps == []
    await client.aclose()


@respx.mock
async def test_429_exhausts_retries():
    client, _ = make_client(retry_attempts=2)
    respx.get(f"{BASE}/api/v0/instances/1/").mock(
        return_value=httpx.Response(429, json={"detail": "too frequent"})
    )
    with pytest.raises(VastRateLimitError):
        await client.request("GET", "/instances/1")
    await client.aclose()


@respx.mock
async def test_transport_error_retries_then_raises():
    client, sleeps = make_client(retry_attempts=2)
    respx.get(f"{BASE}/api/v0/instances/1/").mock(side_effect=httpx.ConnectError("boom"))
    with pytest.raises(VastTransportError):
        await client.request("GET", "/instances/1")
    assert len(sleeps) == 1  # 1 retry com backoff
    await client.aclose()


@respx.mock
async def test_invalid_key_maps_to_auth_error():
    client, _ = make_client()
    # Documentação oficial: 404 com "Invalid user key" na busca de ofertas.
    respx.post(f"{BASE}/api/v0/bundles/").mock(
        return_value=httpx.Response(404, json={"error": "not_found", "msg": "Invalid user key"})
    )
    with pytest.raises(VastAuthError):
        await client.request("POST", "/bundles/", json_body={})
    await client.aclose()


@respx.mock
async def test_offer_unavailable_maps_correctly():
    client, _ = make_client()
    respx.put(f"{BASE}/api/v0/asks/77/").mock(
        return_value=httpx.Response(
            410,
            json={
                "success": False,
                "error": "no_such_ask",
                "msg": "error 410/3907: no_such_ask Instance type 77 is no longer available.",
            },
        )
    )
    with pytest.raises(VastOfferUnavailableError):
        await client.request("PUT", "/asks/77", json_body={"image": "x"})
    await client.aclose()


@respx.mock
async def test_idempotency_replays_same_create():
    client, _ = make_client()
    route = respx.put(f"{BASE}/api/v0/asks/77/").mock(
        return_value=httpx.Response(200, json={"success": True, "new_contract": 123})
    )
    body = {"image": "vastai/pytorch", "disk": 20}
    s1, d1 = await client.request("PUT", "/asks/77", json_body=body, idempotency=True)
    s2, d2 = await client.request("PUT", "/asks/77", json_body=body, idempotency=True)
    assert d1 == d2 and s1 == s2 == 200
    assert route.call_count == 1  # segunda chamada foi replay local
    await client.aclose()


@respx.mock
async def test_idempotency_different_body_creates_twice():
    client, _ = make_client()
    route = respx.put(f"{BASE}/api/v0/asks/77/").mock(
        return_value=httpx.Response(200, json={"success": True, "new_contract": 123})
    )
    await client.request("PUT", "/asks/77", json_body={"image": "a"}, idempotency=True)
    await client.request("PUT", "/asks/77", json_body={"image": "b"}, idempotency=True)
    assert route.call_count == 2
    await client.aclose()


def test_missing_key_raises_before_http():
    config = VastClientConfig(api_key=None)
    client = VastHttpClient(config)
    import asyncio

    async def call():
        await client.request("GET", "/instances/1")

    with pytest.raises(VastAuthError):
        asyncio.run(call())


@respx.mock
async def test_path_gets_v0_prefix_and_trailing_slash():
    client, _ = make_client()
    route = respx.get(f"{BASE}/api/v0/instances/5/").mock(
        return_value=httpx.Response(200, json={"success": True})
    )
    await client.request("GET", "/instances/5")
    assert route.called
    await client.aclose()
