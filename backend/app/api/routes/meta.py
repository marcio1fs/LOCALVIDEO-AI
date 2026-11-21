"""Rotas de saúde e metadados (não autenticadas, sem dados sensíveis)."""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.config import describe_safe

router = APIRouter(tags=["Meta"])


@router.get("/api/v1/health")
async def health() -> dict:
    return {"status": "ok"}


@router.get("/api/v1/meta/config")
async def meta_config(request: Request) -> dict:
    return describe_safe(request.app.state.settings)


@router.get("/api/v1/meta/version")
async def version() -> dict:
    return {"service": "localvideo-ai-control-plane", "version": "0.1.0", "phase": 1}
