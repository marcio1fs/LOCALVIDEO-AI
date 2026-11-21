# Arquitetura — LocalVideo AI (Fase 1)

## Componentes (adendo §2)

| Componente | Tecnologia | Estado |
|---|---|---|
| **Desktop Client** | Tauri 2, React, TypeScript, HTTPS+WS | Fase 5 |
| **Control Plane** | Python, FastAPI, PostgreSQL/Redis (Fase 6) | **Fase 1 — implementado** |
| **GPU Worker** | Linux, NVIDIA, PyTorch, Diffusers, ComfyUI, FFmpeg, volume em `/data` | Fases 2–3 |

O Control Plane **nunca** é instalado na máquina GPU descartável.

## Máquina de estados do GPU Manager (§6)

```
OFF ─start─► STARTING ─plan ok─► PROVISIONING ─container running─► CHECKING ─worker ok─► READY
 │              │                    │                                │                  │
 │              ├─sem ofertas─► HOST_UNAVAILABLE                       │                  ├─► BUSY ⇄ IDLE
 │              ├─volume/host─► VOLUME_UNAVAILABLE                     │                  └─► STOPPING ─► OFFLINE
 │              ├─orçamento─► BUDGET_LIMIT_REACHED                    │
 │              └─erro─► ERROR ◄────────── erro em qualquer etapa ────┘
 └── RECOVERING: reconsulta instâncias ativas na Vast.ai ao reiniciar
```

Transições válidas são impostas por `TRANSITIONS` em `gpu_manager.py`; transição
ilegal levanta `RuntimeError` (defensiva) e o estado permanece.

### Pipeline de `POST /gpu/start` (guardado por asyncio.Lock)

1. Autenticação (chave admin) → 2. Portão de mutações (`LV_VAST_ENABLE_MUTATIONS`)
→ 3. Orçamento (Cost Manager: alerta 70%, bloqueio 90%, reserva de armazenamento)
→ 4. Ofertas compatíveis (`POST /api/v0/bundles/` com filtros de hardware)
→ 5. Afinidade volume↔host físico (volumes locais são vinculados à máquina, §5)
→ 6. Estimativa de custo + reserva → 7. Criação da instância
(`PUT /api/v0/asks/{id}/`, idempotente) → 8. Poll de `running` com detecção do
**poll-trap oficial** (`exited`/`unknown`/`offline`) → 9. Validação do host da
instância criada contra o host do volume → 10. Sonda do worker (Fase 2).

**READY só ocorre com o worker validado** — nunca apenas porque a instância
foi criada. Sem sonda configurada (Fase 1), o estado fica em `CHECKING`.

## Encerramento (§7) — STOP ≠ DESTROY

- `mode="stop"`: instância → `stopped` (para cobrança de GPU; disco continua).
- `mode="destroy"`: exige `data_persisted_confirmed=true`; sem isso, bloqueado.
- Volumes **nunca** são apagados automaticamente (o adaptador nem expõe exclusão).

## Cost Manager (§8)

- Orçamento mensal em BRL; conversão USD→BRL configurável.
- Pools: `reservado` (estimativas ativas) + `gasto real` (settlements +
  cobranças externas). `committed` decide 70%/90%/100%.
- Cobranças reais consolidadas de `GET /api/v0/charges/` (paginada).
- Excedente sobre reserva → registrado como `external_override` com aviso.
- Reserva mínima para armazenamento/tráfego (`LV_STORAGE_RESERVE_BRL`).
- **Não há promessa de limite absoluto de cobrança** — o bloqueio é interno;
  a cobrança efetiva é da Vast.ai (documento de segurança).

## Storage Registry (§5)

Registro (JSON na Fase 1; PostgreSQL na Fase 6) com: id do volume, host físico
(`machine_id`), capacidade, usado, caminho de montagem (`/data`), estado
(`AVAILABLE`, `IN_USE`, `HOST_UNAVAILABLE`, `UNKNOWN`, `DECOMMISSIONED`) e
última verificação. Host indisponível → estado `VOLUME_UNAVAILABLE`/`HOST_UNAVAILABLE`
com dados preservados e opção de tentar novamente ou recuperar por backup.

## Seleção de ofertas (§4)

Filtros estruturados na própria API (VRAM MB, RAM MB, disco, `cuda_max_good`,
`reliability`, `gpu_name in [...]`, `machine_id eq {host do volume}`,
teto de `dph_total`) + filtro semântico com motivo de rejeição por oferta
(`VRAM_INSUFICIENTE`, `CUDA_INCOMPATIVEL`, `HOST_VOLUME_DIFERENTE`, …) +
score composto (preço 45%, confiabilidade 25%, disco 10%, rede 10%, desempenho/$ 10%).
Perfil de hardware totalmente editável (`LV_GPU_PREF_*` ou por requisição).

## Rate limiting e auditoria (§10)

- Janela deslizante em memória por chave/IP (60/min + burst; Redis na Fase 6).
- Auditoria JSON-lines em `data/audit.log` para operações admin/financeiras,
  com blindagem de campos sensíveis.
