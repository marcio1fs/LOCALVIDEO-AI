"""Rotas /api/v1/storage — status do armazenamento persistente (§5/§9)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.schemas.gpu import StorageStatusResponse
from app.security.auth import AuthContext, require_auth

router = APIRouter(prefix="/api/v1/storage", tags=["Armazenamento"])


@router.get("/status", response_model=StorageStatusResponse)
async def storage_status(
    request: Request,
    context: AuthContext = Depends(require_auth),
) -> StorageStatusResponse:
    registry = request.app.state.storage_registry
    settings = request.app.state.settings
    records = await registry.list()
    return StorageStatusResponse(
        volumes=[registry.to_public(record) for record in records],
        mount_path=settings.volume_mount_path,
        note=(
            "Volumes locais da Vast.ai são vinculados ao host físico onde foram "
            "criados. O volume principal NÃO substitui backup — configure backup "
            "externo opcional (Fase 4)."
        ),
    )
