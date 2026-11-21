"""Rotas de geração e biblioteca — reservadas (Fase 3).

Presentes na OpenAPI com contrato estável, respondem 501 enquanto o
Job Manager/worker de inferência não existir. NUNCA simulam sucesso de
geração real (§12/§14 do adendo).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.security.auth import AuthContext, require_auth

router = APIRouter(tags=["Geração (Fase 3)"])

_NOT_IMPLEMENTED_DETAIL = {
    "code": "not_implemented",
    "message": (
        "Pipeline de geração chega na Fase 3 (Job Manager + worker ComfyUI/"
        "Diffusers + FFmpeg). Esta rota está reservada e não simula processamento."
    ),
}


@router.post("/api/v1/generation")
async def create_generation(context: AuthContext = Depends(require_auth)) -> dict[str, Any]:
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=_NOT_IMPLEMENTED_DETAIL)


@router.get("/api/v1/generation/{generation_id}")
async def get_generation(generation_id: str, context: AuthContext = Depends(require_auth)) -> dict[str, Any]:
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=_NOT_IMPLEMENTED_DETAIL)


@router.post("/api/v1/generation/{generation_id}/cancel")
async def cancel_generation(generation_id: str, context: AuthContext = Depends(require_auth)) -> dict[str, Any]:
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=_NOT_IMPLEMENTED_DETAIL)


@router.get("/api/v1/library/videos")
async def library_videos(context: AuthContext = Depends(require_auth)) -> dict[str, Any]:
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=_NOT_IMPLEMENTED_DETAIL)
