# Relatório — Fase 1: Fundação do Control Plane + Adaptador Vast.ai

**Data:** 2026-11-21 · **Status:** concluída · **Cobrança real nesta fase: R$ 0,00**
(nenhuma instância foi criada; portão de mutações fechado por padrão)

---

## 1. Arquivos criados

### Backend — aplicação (`backend/app/`)
| Arquivo | Conteúdo |
|---|---|
| `config.py` | Configuração `LV_*` com pydantic-settings; fail-closed; portão `LV_VAST_ENABLE_MUTATIONS`; perfil de hardware editável |
| `main.py` | Fábrica FastAPI, montagem de serviços, CORS, handlers de erro com envelope estável |
| `api/routes/gpu.py` | `GET /gpu/status`, `POST /gpu/start`, `POST /gpu/stop`, `POST /gpu/offers`, `GET /gpu/cost-estimate`, `GET /gpu/usage`, `GET /gpu/hardware-profile` |
| `api/routes/storage.py` | `GET /storage/status` |
| `api/routes/generation.py` | `/generation`, `/library/videos` — **reservadas, 501** (nada simulado) |
| `api/routes/meta.py` | `/health`, `/meta/config` (sem segredos), `/meta/version` |
| `security/auth.py` | `X-API-Key`/Bearer, papéis client/admin, tempo constante, fail-closed 503 |
| `security/rate_limit.py` | Janela deslizante por chave/IP, 429 + Retry-After |
| `security/audit.py` | Auditoria JSON-lines com blindagem de campos sensíveis |
| `schemas/gpu.py` | Contratos de requisição/resposta (OpenAPI gerado em `/docs`) |
| `services/gpu_manager.py` | 13 estados (§6), pipeline guardado, plan/estimate, stop/destroy, recover |
| `services/cost_manager.py` | Orçamento BRL, alerta 70% / bloqueio 90% / limite 100%, reservas, cobranças reais e externas |
| `services/offer_selector.py` | Filtros do §4 + motivo de rejeição + score composto |
| `services/storage_registry.py` | Registro de volumes (host físico, `/data`, estado, última verificação) |

### Backend — adaptador Vast.ai isolado (`backend/providers/vast/`)
`vast_client.py` · `vast_offers.py` · `vast_instances.py` · `vast_volumes.py` ·
`vast_billing.py` · `vast_schemas.py` · `vast_exceptions.py`
(retry/backoff com semântica oficial, idempotência local de mutações, portão
de cobrança, afinidade de volume, poll-trap, mapeamento tipado de erros)

### Testes (`backend/tests/`, 104 testes)
`conftest.py` (fakes sem rede) · `test_vast_client.py` · `test_vast_services.py` ·
`test_offer_selector.py` · `test_gpu_manager.py` · `test_cost_manager.py` ·
`test_storage_registry.py` · `test_api.py`

### Infra e docs
`.env.example` (comentado, PT-BR) · `.gitignore` · `Makefile` · `docker-compose.yml`
(PostgreSQL/Redis reservados p/ Fase 6) · `backend/pyproject.toml` · `backend/requirements.txt`
· `README.md` · `docs/ARQUITETURA.md` · `docs/API-VAST-MAPEAMENTO.md` ·
`docs/SEGURANCA.md` · `docs/FASES.md` · este relatório

## 2. Alterações no repositório

Partiu-se do commit inicial (`README.md` de 1 linha). Não havia código
existente a alterar — toda a base foi criada nesta fase, na branch
`arena/77cd3491-localvideo-ai`.

## 3. Testes executados e resultados

```
$ make test
104 passed, 1 warning in ~2.5s      (backend)
$ make lint
All checks passed!                  (ruff)
```

Cobertura dos cenários obrigatórios do §12 atingíveis com mocks nesta fase:

| Cenário §12 | Teste | Resultado |
|---|---|---|
| Credenciais inválidas | `test_invalid_key_maps_to_auth_error`, `test_invalid_key_rejected`, 401/403/503 na API | ✅ |
| Oferta sem VRAM suficiente | `test_offer_with_insufficient_vram_rejected` | ✅ |
| Oferta sem compatibilidade CUDA | `test_offer_without_cuda_compatibility_rejected` | ✅ |
| Volume incompatível com o host | `test_volume_host_affinity_mismatch`, `test_volume_of_different_host_goes_volume_unavailable`, `test_instance_host_mismatch_after_create_raises` | ✅ |
| Host indisponível | `test_no_compatible_offer_goes_host_unavailable` | ✅ |
| Falha ao criar instância | `test_instance_create_failure_raises`, `test_offer_unavailable_maps_correctly` | ✅ |
| Falha ao inicializar worker | `test_start_with_failing_worker_goes_error` | ✅ |
| GPU desligada durante solicitação (poll-trap) | `test_wait_for_running_poll_trap`, `test_poll_trap_goes_error` | ✅ |
| Duas solicitações simultâneas | `test_simultaneous_starts_only_one_provisions` (1 instância criada) | ✅ |
| Orçamento excedido | `test_block_at_90_percent`, `test_limit_reached_blocks_everything`, `test_budget_exceeded_blocks_start` | ✅ |
| Cancelamento / geração / FFmpeg / salvar vídeo | **Fase 3** (rotas reservadas 501) | ⏳ |
| Recuperação de sessão | `test_recover_finds_running_instance` | ✅ (fake; real na Fase 2) |
| Encerramento automático | **Fase 4** | ⏳ |
| Persistência após destruição | `test_destroy_requires_persistence_confirmation` + registro sobrevive (JSON) | ✅ (fake; real na Fase 2) |
| Retry/backoff, Retry-After, quota diária | `test_retry_on_502_then_success`, `test_retry_on_429_honors_retry_after`, `test_search_quota_429_not_retried` | ✅ |
| Idempotência (retry não duplica contrato) | `test_idempotency_replays_same_create` | ✅ |
| Rate limiting da API própria | `test_rate_limit_429` | ✅ |
| Segredos fora de logs/respostas | `test_meta_config_has_no_secrets` | ✅ |

**Nenhum teste simula sucesso de geração real** — a geração é 501 até a Fase 3.

Smoke test do servidor real (uvicorn, preview): health 200; sem chave → 401;
`/gpu/offers` sem `VAST_API_KEY` → 503 `vast_key_missing`; `start` com admin
sem chave Vast → estado OFFLINE com `vast_key_missing`; `/generation` → 501.

## 4. Problemas encontrados (e como foram resolvidos)

1. **Doc oficial ambígua no método de criação** (`PUT /api/v0/asks/{id}` nos
   exemplos; quirk do OpenAPI cita `POST /asks/{id}/`). Resolvido seguindo o
   SDK oficial (`client.put(f"/asks/{id}/", ...)`) — `PUT`.
2. **Scoring de preço normalizado por oferta** produzia comparações
   inconsistentes; corrigido para normalizar entre as ofertas sobreviventes.
3. **Contabilidade de reservas × liquidações** poderia zerar custo real;
   refeita com pools (`reservado` + `gasto real`) e replay do ledger.
4. **Guarda de concorrência incompleta**: segunda chamada a `start()` com
   sessão `READY` passaria pelo check; adicionado rejeição
   `session_already_active` (evita duplicar cobrança).
5. **Transições de falha incompletas** (`CHECKING → VOLUME_UNAVAILABLE`,
   `OFFLINE → RECOVERING`) bloqueavam caminhos de erro legítimos; tabela
   atualizada.
6. **Anotações lazy do FastAPI** (`from __future__ import annotations`) com
   `Request` não importado gerava erro 422 silencioso; corrigido.
7. Endpoint de saldo (`users/current`): **shape não documentado em detalhe** —
   mantido como diagnóstico defensivo; validação real fica para a Fase 6.

## 5. Custos potenciais

| Item | Valor | Quando |
|---|---|---|
| **Fase 1 (esta)** | **R$ 0** — apenas chamadas de leitura à API em modo dev; mutações fechadas | — |
| RTX 4090 (referência mercado atual) | ≈ US$ 0,35–0,55/h (≈ R$ 1,90–3,00/h) | Fase 2 em diante, com orçamento de R$ 100/mês |
| Armazenamento em volume | ≈ US$ 0,10–0,15/GB/mês (ex.: 100 GB ≈ US$ 10–15 ≈ R$ 54–81/mês) | se volume contratado |
| Transferência | cobrada por TB conforme região (ver oferta `inet_*_cost`) | por uso |

O Cost Manager bloqueia novas sessões em 90% do orçamento e reserva margem
para armazenamento/tráfego. **Não há garantia de limite absoluto de cobrança** —
a cobrança efetiva é da Vast.ai (ver `docs/SEGURANCA.md`).

## 6. Próxima fase (Fase 2)

1. Bootstrap real do worker na instância (imagem PyTorch, sonda de
   prontidão: `nvidia-smi`, CUDA, espaço em disco) → READY com validação real.
2. Montagem confirmada do volume em `/data` (verificação após `running`).
3. `RECOVERING` real (reconciliação com instâncias ativas da conta).
4. WebSocket `/ws/gpu` com eventos de estado/custo para o desktop.
5. Primeiro teste real **controlado**: exigirá chave Vast.ai do usuário,
   `LV_VAST_ENABLE_MUTATIONS=true`, orçamento configurado e custo estimado
   confirmado — com instância destruída ao final.
