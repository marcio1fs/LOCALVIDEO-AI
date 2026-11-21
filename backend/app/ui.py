"""Painel web do Control Plane (antecipação da Fase 5 — §11).

Serve o dashboard (HTML/CSS/JS vanilla, sem build) a partir de `app/static/`:

- Painel GPU Cloud: estado, iniciar/encerrar sessão (com confirmação de
  custo e de persistência), provedor, GPU/VRAM, tempo de sessão, custo,
  fila, encerramento automático, ofertas e histórico.
- Painel de orçamento com limite mensal configurável (PATCH admin).
- Alertas de inicialização/prontidão/volume/host/orçamento (§11).

A página usa URLs RELATIVAS (funciona sob proxy do preview e em produção) e
a chave digitada permanece apenas em memória no navegador. `/` é público e
não expõe segredos; os dados do painel vêm das rotas autenticadas.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

router = APIRouter(tags=["Painel"])

STATIC_DIR = Path(__file__).parent / "static"


@router.get("/", include_in_schema=True)
async def dashboard() -> FileResponse:
    """Dashboard completo (público; dados sensíveis exigem X-API-Key)."""
    return FileResponse(STATIC_DIR / "index.html", media_type="text/html")
