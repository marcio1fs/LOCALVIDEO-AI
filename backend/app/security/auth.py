"""Autenticação da API própria do LocalVideo AI.

- O desktop client envia `X-API-Key: <chave>` (ou Authorization: Bearer).
- Chave de cliente: rotas de leitura e geração.
- Chave admin: operações que geram cobrança (start/stop/destroy).
- Comparação em tempo constante; nenhuma chave é logada.
- Fail-closed: sem chave configurada, rotas autenticadas respondem 503.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Any

from fastapi import Depends, HTTPException, Request, status

from app.config import Settings


@dataclass(frozen=True)
class AuthContext:
    """Contexto autenticado da requisição (sem material sensível)."""

    role: str  # "client" | "admin"
    label: str  # rótulo não sensível p/ auditoria, ex.: "client-key"

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


class KeyVerifier:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def client_key(self) -> str | None:
        return self.settings.localvideo_api_key

    @property
    def admin_key(self) -> str | None:
        return self.settings.localvideo_admin_api_key or self.settings.localvideo_api_key

    def fail_closed(self) -> bool:
        """Sem nenhuma chave configurada: rotas autenticadas ficam indisponíveis."""
        return self.client_key is None and not self.settings.allow_insecure_dev

    def verify(self, presented: str | None) -> AuthContext:
        if presented is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Autenticação ausente: envie o header X-API-Key.",
                headers={"WWW-Authenticate": "ApiKey"},
            )
        if self.fail_closed():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "Serviço sem chaves de API configuradas "
                    "(LV_LOCALVIDEO_API_KEY). Autenticação indisponível."
                ),
            )

        client = self.client_key
        if client is not None and secrets.compare_digest(presented, client):
            return AuthContext(role="client", label="client-key")

        admin = self.admin_key
        if admin is not None and secrets.compare_digest(presented, admin):
            return AuthContext(role="admin", label="admin-key")

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Chave de API inválida.",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    def require_admin(self, context: AuthContext) -> AuthContext:
        if not context.is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Operação exige chave admin do LocalVideo AI.",
            )
        return context


def _extract_key(request: Request) -> str | None:
    header_key = request.headers.get("x-api-key")
    if header_key:
        return header_key
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


def get_verifier(request: Request) -> KeyVerifier:
    return request.app.state.verifier


def require_auth(request: Request, verifier: KeyVerifier = Depends(get_verifier)) -> AuthContext:
    """Dependência padrão: rota autenticada (qualquer papel válido)."""
    return verifier.verify(_extract_key(request))


def require_admin_auth(
    request: Request,
    verifier: KeyVerifier = Depends(get_verifier),
) -> AuthContext:
    """Dependência para operações que geram cobrança (start/stop/destroy)."""
    context = verifier.verify(_extract_key(request))
    return verifier.require_admin(context)


def audit_fields(context: AuthContext) -> dict[str, Any]:
    """Campos seguros para registrar em auditoria."""
    return {"role": context.role, "label": context.label}
