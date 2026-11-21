# LOCALVIDEO AI

Criador de vídeos com IA. O aplicativo roda no Windows do usuário (Tauri 2); toda a
inferência de vídeo acontece remotamente em GPUs NVIDIA alugadas sob demanda
(Vast.ai), orquestradas por um Control Plane próprio.

**Status: Fase 1 concluída** — fundação do Control Plane + adaptador Vast.ai com
testes. Nenhuma operação que gere cobrança está habilitada por padrão.

```
┌─────────────────────┐   HTTPS + WebSocket (Fase 5)   ┌──────────────────────────┐
│  Desktop Client     │ ─────────────────────────────► │  Control Plane           │
│  Tauri 2 / React    │   chave LocalVideo AI no       │  FastAPI (este repo,     │
│  (Fase 5)           │   Windows Credential Manager   │  backend/)               │
└─────────────────────┘                                │  ┌────────────────────┐  │
                                                       │  │ GPU Manager        │  │
                                                       │  │ Cost Manager       │  │
                                                       │  │ Storage Manager    │  │
                                                       │  │ Vast.ai adapter    │  │
                                                       │  └────────────────────┘  │
                                                       └───────────┬──────────────┘
                                              chave Vast.ai        │ REST (Bearer)
                                        (só no servidor, §3)       ▼
                                                       ┌──────────────────────────┐
                                                       │  GPU Worker (Vast.ai)    │
                                                       │  Linux + NVIDIA + CUDA   │
                                                       │  PyTorch/Diffusers/      │
                                                       │  ComfyUI/FFmpeg (Fase 3) │
                                                       │  Volume persistente      │
                                                       │  montado em /data (§5)   │
                                                       └──────────────────────────┘
```

## Fases (adendo §14 — entrega incremental)

| Fase | Escopo | Status |
|------|--------|--------|
| **1** | Fundação: Control Plane FastAPI, adaptador Vast.ai completo (client/offers/instances/volumes/billing/schemas/exceptions) com retry+idempotência, autenticação, rate limit, Cost Manager (70%/90%), GPU Manager (13 estados + pipeline guardado), Storage Registry, OpenAPI, ~104 testes com mocks | ✅ concluída |
| 2 | Provisionamento automático completo: criação real, montagem do volume, bootstrap do worker, validação de GPU/CUDA, WebSocket | ⏳ próxima |
| 3 | Job Manager + POST /generation + worker de inferência (ComfyUI/Diffusers) + FFmpeg + biblioteca | ⏳ |
| 4 | GPU Idle Manager (encerramento automático), backup externo opcional | ⏳ |
| 5 | Desktop app Tauri 2 (painéis GPU Cloud e orçamento, Credential Manager) | ⏳ |
| 6 | PostgreSQL + Redis, auditoria, testes reais controlados com GPU alugada | ⏳ |

Relatório completo da Fase 1: [`docs/RELATORIO-FASE-1.md`](docs/RELATORIO-FASE-1.md).

## Estrutura do backend

```
backend/
├── app/
│   ├── config.py                # configuração LV_* (fail-closed, segredos fora de logs)
│   ├── main.py                  # fábrica FastAPI + montagem de serviços
│   ├── api/routes/              # gpu, storage, generation (reservada), meta
│   ├── security/                # auth (X-API-Key/Bearer), rate limit, auditoria
│   ├── schemas/                 # modelos de requisição/resposta
│   └── services/
│       ├── gpu_manager.py       # máquina de estados de 13 estados + pipeline
│       ├── cost_manager.py      # orçamento BRL, 70%/90%, reservas/liquidações
│       ├── offer_selector.py    # filtro por VRAM/CUDA/host/reliability + score
│       └── storage_registry.py  # registro de volumes (host físico, /data)
├── providers/vast/              # ADAPTADOR ISOLADO (§3) — nada de Vast fora daqui
│   ├── vast_client.py           # HTTP + retry/backoff + idempotência local
│   ├── vast_offers.py           # POST /api/v0/bundles/
│   ├── vast_instances.py        # asks/{id}, instances/{id}, poll-trap, destroy guard
│   ├── vast_volumes.py          # volumes + afinidade host físico (§5)
│   ├── vast_billing.py          # GET /api/v0/charges/ (cobranças reais)
│   ├── vast_schemas.py          # modelos espelhando a API oficial
│   └── vast_exceptions.py       # erros tipados mapeados
└── tests/                       # 104 testes (mocks/respx — zero cobrança)
```

## Como rodar

```bash
# 1. Dependências
make install                     # venv + requirements

# 2. Configuração
cp .env.example .env             # edite as chaves (ver .env.example)

# 3. Servidor de desenvolvimento
make run                         # http://localhost:8000  |  docs em /docs

# 4. Testes e lint
make test
make lint
```

Abrindo `http://localhost:8000/` você acessa o **painel web completo** (antecipação
da Fase 5): estado da GPU, iniciar/encerrar sessão com confirmação de custo,
orçamento configurável, armazenamento, ofertas em tempo real e histórico —
detalhes em [`docs/PAINEL-WEB.md`](docs/PAINEL-WEB.md). Conecte no topo com a
chave de API; operações de cobrança exigem a chave admin.

Sem `LV_VAST_API_KEY`, o sistema responde claramente `503 vast_key_missing`
nas rotas que dependem do provedor — nada é simulado como se fosse real.

### Portão de cobrança (§14)

Por padrão `LV_VAST_ENABLE_MUTATIONS=false`: **nenhuma** instância/volume é
criado, alterado ou destruído. Para habilitar operações reais é preciso,
juntos: (1) chave Vast.ai configurada, (2) flag explícita `true`,
(3) autenticação com a chave admin, (4) `confirm_cost: true` na requisição e
(5) saldo de orçamento suficiente (bloqueio em 90%, alerta em 70%).

## Documentação

- [`docs/ARQUITETURA.md`](docs/ARQUITETURA.md) — componentes, estados, pipeline
- [`docs/API-VAST-MAPEAMENTO.md`](docs/API-VAST-MAPEAMENTO.md) — endpoints REST da Vast.ai usados, com fontes oficiais
- [`docs/SEGURANCA.md`](docs/SEGURANCA.md) — modelo de ameaças e medidas (§10)
- [`docs/PAINEL-WEB.md`](docs/PAINEL-WEB.md) — painel web completo (antecipação da Fase 5)
- [`docs/FASES.md`](docs/FASES.md) — plano detalhado por fase
- [`docs/RELATORIO-FASE-1.md`](docs/RELATORIO-FASE-1.md) — arquivos, testes, resultados, riscos e custos
