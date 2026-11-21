# Mapeamento da API REST da Vast.ai — Fontes oficiais (regra §14: não inventar parâmetros)

Todas as chamadas do adaptador (`backend/providers/vast/`) foram validadas
contra a documentação oficial e o código-fonte do SDK/CLI oficial
(`github.com/vast-ai/vast-cli` — `vastai/api/client.py`, `instances.py`,
`storage.py`, `billing.py`, `offers.py`).

## Base e autenticação

- Servidor: `https://console.vast.ai`
- Header: `Authorization: Bearer <VAST_API_KEY>` (todos os endpoints)
- Paths sem prefixo recebem `/api/v0` automaticamente (comportamento do SDK).
- `gpu_ram` em MB na API REST (CLI converte GB→MB — quirk oficial).

## Endpoints utilizados na Fase 1

| Operação | Método + path | Observações validadas |
|---|---|---|
| Buscar ofertas | `POST /api/v0/bundles/` | Filtros como `{op: valor}` (`eq`,`neq`,`gt`,`lt`,`gte`,`lte`,`in`,`notin`); `type` ∈ on-demand/bid/reserved; `order` como `[["dph_total","asc"]]`; `allocated_storage` para precificar disco; defaults oficiais `verified/external/rentable/rented`. Resposta: `{"offers": [...]}`. |
| Criar instância | `PUT /api/v0/asks/{offer_id}/` | Body oficial: `client_id:"me"`, `image` (obrigatório), `disk`, `env` (dict), `label`, `runtype`, `args`, `onstart`, `cancel_unavail`, `force`, `target_state`, `volume_info`. Resposta: `{"success": true, "new_contract": <id>}` — o ID da instância é `new_contract`. |
| Consultar instância | `GET /api/v0/instances/{id}/` (query `owner=me`) | `actual_status` ∈ null, created, loading, running, stopped, frozen, exited, rebooting, unknown, offline. |
| Listar instâncias | `GET /api/v1/instances/` | Paginação por keyset (máx. 25/página, `after_token`/`next_token`). |
| Iniciar/parar | `PUT /api/v0/instances/{id}/` | Body `{"state": "running"|"stopped"}` (manage-instance). |
| Destruir | `DELETE /api/v0/instances/{id}/` | Irreversível — exige confirmação local de persistência. |
| Listar volumes | `GET /api/v0/volumes` (query `owner=me`, `type=all`) | Volume tem `machine_id` = host físico ao qual está vinculado. |
| Alugar volume | `PUT /api/v0/volumes/` | Body `{"id": <offer_id>, "size": <GB>}` → `{"volume_name": "V.x"}`. |
| Cobranças | `GET /api/v0/charges/` | `select_filters` obrigatório com `day` (unix UTC) e opcional `type in [instance, volume]`; paginação `after_token` (máx. 500). Retorna `amount` por contrato. |
| Conta (diagnóstico) | `GET /api/v0/users/current` | Shape defensivo (saldo validado em teste real, Fase 6). |
| Associar volume à instância | campo `volume_info` no create | Forma validada no SDK (`build_volume_info`): `{"mount_path": "/data", "create_new": false, "volume_id": <id>, "size"?: n, "name"?: s}`. |

## Semântica de retry (espelhando o SDK oficial)

- Retentáveis: **429** (exceto quota diária de busca `search_quota_exceeded`),
  **502, 503, 504**, erros de transporte (conexão/timeout).
- `Retry-After` é respeitado (até `LV_VAST_MAX_RETRY_AFTER_SECONDS`).
- Backoff exponencial `base × fator^tentativa` + jitter.
- 4xx restantes **não** são retentáveis (ex.: `no_such_ask` 400/404/410).

## Regras críticas documentadas pelo próprio provedor

1. **Poll-trap**: se `actual_status` virar `exited`, `unknown` ou `offline`,
   a instância **nunca** chegará a `running` — detectamos e sinalizamos
   `VastInstanceUnrecoverableError` (destruição só com confirmação).
2. **Volumes locais são vinculados ao host físico** — não podem ser anexados a
   instâncias de outra máquina. Imposto por `validate_host_affinity` e filtro
   `machine_id eq {host}` na busca.
3. **Cobrança de armazenamento começa na criação**; cobrança de GPU começa
   quando o status chega a `running`.
4. **Criar instância**: sempre ler `new_contract` (não `id`).

## Fontes

- https://docs.vast.ai/api-reference/search/search-offers.md
- https://docs.vast.ai/api-reference/instances/create-instance.md
- https://docs.vast.ai/api-reference/instances/show-instances.md
- https://docs.vast.ai/api-reference/instances/manage-instance.md
- https://docs.vast.ai/api-reference/instances/destroy-instance.md
- https://docs.vast.ai/api-reference/volumes/list-volumes.md
- https://docs.vast.ai/api-reference/volumes/rent-volume.md
- https://docs.vast.ai/api-reference/billing/show-charges.md
- https://docs.vast.ai/guides/instances/storage/volumes (afinidade de volume)
- https://raw.githubusercontent.com/vast-ai/vast-cli/master/vastai/SKILL.md
- https://raw.githubusercontent.com/vast-ai/vast-cli/master/vastai_sdk/SKILL.md
- Código oficial: `vastai/api/client.py` (retry/idempotência), `instances.py`
  (`build_create_instance_payload`, `build_volume_info`), `storage.py`,
  `billing.py`, `offers.py`
