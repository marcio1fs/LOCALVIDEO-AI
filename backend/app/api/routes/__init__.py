"""Agregador das rotas da API v1."""

from fastapi import APIRouter

from .generation import router as generation_router
from .gpu import router as gpu_router
from .meta import router as meta_router
from .storage import router as storage_router

api_router = APIRouter()
api_router.include_router(meta_router)
api_router.include_router(gpu_router)
api_router.include_router(storage_router)
api_router.include_router(generation_router)
