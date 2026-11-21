"""Testes da API v1: autenticação, rate limit, portão de mutações, contratos."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import FakeOffersService, make_offer, make_settings


def seed_registry(tmp_path, volumes: list[dict]) -> None:
    """Semeia o registro de armazenamento via arquivo (sem cross-loop)."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "storage_registry.json").write_text(json.dumps(volumes), encoding="utf-8")


@pytest.fixture
def app(tmp_path):
    settings = make_settings(tmp_path, vast_api_key="test-vast-key")
    return create_app(settings)


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Health / meta (sem autenticação)
# ---------------------------------------------------------------------------


def test_health_open(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_meta_config_has_no_secrets(client):
    response = client.get("/api/v1/meta/config")
    body = str(response.json())
    assert "dev-client-key" not in body
    assert "test-vast-key" not in body
    assert response.json()["vast_api_key_configured"] is True


# ---------------------------------------------------------------------------
# Autenticação (§9/§10)
# ---------------------------------------------------------------------------


def test_status_requires_auth(app, client):
    response = client.get("/api/v1/gpu/status")
    assert response.status_code == 401


def test_status_with_client_key(client):
    response = client.get("/api/v1/gpu/status", headers={"X-API-Key": "dev-client-key"})
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "OFFLINE"
    assert body["provider"] == "vast.ai"
    assert body["mutations_enabled"] is True


def test_invalid_key_rejected(client):
    response = client.get("/api/v1/gpu/status", headers={"X-API-Key": "wrong-key"})
    assert response.status_code == 401


def test_admin_operation_requires_admin_key(app, client):
    response = client.post(
        "/api/v1/gpu/start",
        json={"confirm_cost": True},
        headers={"X-API-Key": "dev-client-key"},
    )
    assert response.status_code == 403


def test_fail_closed_without_any_key(tmp_path):
    settings = make_settings(tmp_path, localvideo_api_key=None, localvideo_admin_api_key=None)
    app = create_app(settings)
    with TestClient(app) as client:
        response = client.get("/api/v1/gpu/status", headers={"X-API-Key": "anything"})
        assert response.status_code == 503
        # health continua acessível
        assert client.get("/api/v1/health").status_code == 200


# ---------------------------------------------------------------------------
# Portão de mutações (§14: sem cobrança acidental)
# ---------------------------------------------------------------------------


def test_start_blocked_when_mutations_disabled(tmp_path):
    settings = make_settings(tmp_path, vast_enable_mutations=False, vast_api_key="test-vast-key")
    app = create_app(settings)
    # Ofertas fake: o pipeline chega até a criação, onde o portão bloqueia.
    app.state.gpu_manager.offers = FakeOffersService([make_offer()])
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/gpu/start",
            json={"confirm_cost": True},
            headers={"X-API-Key": "dev-admin-key"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "ERROR"  # vast_mutations_disabled -> ERROR
    assert body["instance_id"] is None


def test_start_without_vast_key_reports_missing(tmp_path):
    settings = make_settings(tmp_path, vast_api_key=None, vast_enable_mutations=True)
    app = create_app(settings)
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/gpu/start",
            json={"confirm_cost": True},
            headers={"X-API-Key": "dev-admin-key"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["state"] == "OFFLINE"
        assert body["errors"] == ["vast_key_missing"]


def test_offers_without_vast_key_503(tmp_path):
    settings = make_settings(tmp_path, vast_api_key=None)
    app = create_app(settings)
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/gpu/offers",
            json={"requirements": None},
            headers={"X-API-Key": "dev-client-key"},
        )
        assert response.status_code == 503


# ---------------------------------------------------------------------------
# Rotas de leitura com Vast.ai mockado (respx)
# ---------------------------------------------------------------------------


def test_offers_with_mocked_vast(app, client):
    app.state.gpu_manager.offers = FakeOffersService([make_offer()])
    response = client.post(
        "/api/v1/gpu/offers",
        json={"requirements": None, "estimated_hours": 1.0},
        headers={"X-API-Key": "dev-client-key"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["feasible"] is True
    assert body["offer"]["gpu_name"] == "RTX 4090"
    assert body["cost_estimate"]["total_brl"] > 0


def test_cost_estimate_with_mocked_vast(app, client):
    app.state.gpu_manager.offers = FakeOffersService([make_offer(dph_total=0.50)])
    response = client.get(
        "/api/v1/gpu/cost-estimate?estimated_hours=2",
        headers={"X-API-Key": "dev-client-key"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["cost_estimate"]["gpu_total_usd"] == pytest.approx(1.0)
    assert body["cost_estimate"]["total_brl"] == pytest.approx(2 * 0.50 * 5.40, rel=0.01)


def test_cost_estimate_volume_affinity(tmp_path):
    seed_registry(
        tmp_path,
        [
            {
                "volume_id": 42,
                "machine_id": 999,
                "capacity_gb": 100.0,
                "mount_path": "/data",
                "state": "AVAILABLE",
                "used_gb": 0.0,
                "storage_monthly_usd": 0.0,
            }
        ],
    )
    settings = make_settings(tmp_path, vast_api_key="test-vast-key")
    app = create_app(settings)
    app.state.gpu_manager.offers = FakeOffersService([make_offer(machine_id=555)])
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/gpu/cost-estimate",
            headers={"X-API-Key": "dev-client-key"},
        )
    body = response.json()
    # Volume no host 999 e ofertas só no host 555 -> inviável
    assert body["feasible"] is False


def test_gpu_usage_shape(client):
    response = client.get("/api/v1/gpu/usage", headers={"X-API-Key": "dev-client-key"})
    assert response.status_code == 200
    body = response.json()
    assert "budget" in body and "ledger" in body and "history" in body


def test_storage_status(tmp_path):
    seed_registry(
        tmp_path,
        [
            {
                "volume_id": 42,
                "machine_id": 555,
                "capacity_gb": 100.0,
                "mount_path": "/data",
                "state": "AVAILABLE",
                "used_gb": 0.0,
                "storage_monthly_usd": 0.0,
            }
        ],
    )
    settings = make_settings(tmp_path, vast_api_key="test-vast-key")
    app = create_app(settings)
    with TestClient(app) as client:
        response = client.get("/api/v1/storage/status", headers={"X-API-Key": "dev-client-key"})
    assert response.status_code == 200
    body = response.json()
    assert body["mount_path"] == "/data"
    assert body["volumes"][0]["volume_id"] == 42


def test_hardware_profile_editable(client):
    response = client.get("/api/v1/gpu/hardware-profile", headers={"X-API-Key": "dev-client-key"})
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["allowed_gpus"], list)
    assert "RTX 4090" in body["allowed_gpus"]


# ---------------------------------------------------------------------------
# Rotas de geração: reservadas (501) — nunca simulam sucesso (§12)
# ---------------------------------------------------------------------------


def test_generation_routes_not_implemented(client):
    headers = {"X-API-Key": "dev-client-key"}
    assert client.post("/api/v1/generation", json={}, headers=headers).status_code == 501
    assert client.get("/api/v1/generation/abc", headers=headers).status_code == 501
    assert client.post("/api/v1/generation/abc/cancel", headers=headers).status_code == 501
    assert client.get("/api/v1/library/videos", headers=headers).status_code == 501


# ---------------------------------------------------------------------------
# Rate limiting (§10)
# ---------------------------------------------------------------------------


def test_rate_limit_429(tmp_path):
    settings = make_settings(tmp_path, rate_limit_requests_per_minute=3, rate_limit_burst=0)
    app = create_app(settings)
    with TestClient(app) as client:
        responses = [
            client.get("/api/v1/gpu/status", headers={"X-API-Key": "dev-client-key"})
            for _ in range(5)
        ]
        statuses = [r.status_code for r in responses]
        assert 429 in statuses
        assert statuses[0] == 200


def test_rate_limit_health_exempt(tmp_path):
    settings = make_settings(tmp_path, rate_limit_requests_per_minute=1, rate_limit_burst=0)
    app = create_app(settings)
    with TestClient(app) as client:
        for _ in range(5):
            assert client.get("/api/v1/health").status_code == 200


# ---------------------------------------------------------------------------
# Erros Vast.ai mapeados na API
# ---------------------------------------------------------------------------


def test_offers_auth_error_maps_502(app, client):
    from providers.vast import VastAuthError

    app.state.gpu_manager.offers = FakeOffersService(error=VastAuthError("Invalid user key"))
    response = client.post(
        "/api/v1/gpu/offers", json={}, headers={"X-API-Key": "dev-client-key"}
    )
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "vast_auth_error"
