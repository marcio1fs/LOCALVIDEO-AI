# Plano de fases — implementação incremental (adendo §14)

Regra de ouro: **uma fase por vez, cada módulo testado e documentado**.
Nada de contratação automática de GPU durante desenvolvimento; mocks nos
testes de integração, com clareza sobre o que é simulado.

## Fase 1 — Fundação do Control Plane + adaptador Vast.ai ✅

- Adaptador isolado `providers/vast/` com os 7 módulos exigidos.
- Autenticação da API própria (client/admin), rate limiting, auditoria.
- Cost Manager: orçamento BRL, 70%/90%, reservas/liquidações, cobranças reais.
- GPU Manager: 13 estados, pipeline guardado, seleção de ofertas, estimativa.
- Storage Registry (§5) com afinidade de host físico.
- Rotas `/api/v1/gpu/*`, `/api/v1/storage/status`, meta; geração reservada (501).
- 104 testes (unidade + API) com mocks — **nenhuma cobrança**.

## Fase 2 — Provisionamento automático completo

- `POST /gpu/start` fim-a-fim: criação real → volume em `/data` → bootstrap do
  worker no contêiner (Docker image PyTorch) → validação de GPU/CUDA/disco
  → sonda de prontidão real → READY.
- `POST /gpu/stop` completo + `RECOVERING` (recuperação de sessão).
- Comunicação autenticada Control Plane ↔ Worker (token efêmero).
- WebSocket `/ws/gpu` para eventos ao desktop.
- Testes de integração com sandbox simulado + primeiro teste real CONTROLADO
  (chave própria do usuário, orçamento explícito, instância de menor custo,
  destruída ao final).

## Fase 3 — Job Manager + geração real

- `POST /generation`, `GET /generation/{id}`, cancel, biblioteca de vídeos.
- Worker de inferência: ComfyUI/Diffusers (texto→vídeo), FFmpeg para encode.
- Fila com `GPU_MAX_CONCURRENT_JOBS`; salvamento no volume; thumbnails.
- `GET /library/videos` servido do volume.
- Testes: falha de geração, cancelamento, falha FFmpeg, falha ao salvar.

## Fase 4 — Idle Manager + backup

- Encerramento automático após `GPU_IDLE_TIMEOUT_MINUTES` (padrão 10).
- Regras: não encerrar com geração em curso, FFmpeg finalizando, gravação ou
  transferência pendente; confirmação do worker antes do desligamento.
- Backup externo opcional (Cloud Sync/S3) + documentação de que o volume não
  substitui backup.

## Fase 5 — Desktop app (Tauri 2)

- Painel GPU Cloud: estado, iniciar/encerrar sessão, provedor, GPU, VRAM,
  estado do volume, espaço, tempo, custo estimado/mensal, fila, histórico,
  alertas (§11).
- Painel de orçamento com limite mensal configurável.
- Chave LocalVideo AI no Windows Credential Manager.
- WebSocket para eventos; avisos de inicialização/prontidão/falhas.

## Fase 6 — Persistência e hardening

- PostgreSQL (jobs, sessões, auditoria, volumes) + Redis (fila/rate limit).
- Rotação e revogação de chaves; testes reais controlados de ponta a ponta
  (critérios de aceitação §13, um por um).
