# Segurança — Control Plane (adendo §10)

## Modelo de segredos

| Segredo | Onde vive | Quem vê |
|---|---|---|
| Chave da Vast.ai | somente no servidor de controle (`LV_VAST_API_KEY`) | Control Plane apenas — **nunca** enviado ao desktop |
| Chave de cliente LocalVideo AI | servidor + Windows Credential Manager do desktop (Fase 5) | Control Plane + usuário |
| Chave admin LocalVideo AI | somente servidor (`LV_LOCALVIDEO_ADMIN_API_KEY`) | operações que geram cobrança |
| Credenciais PostgreSQL/Redis | servidor (Fase 6) | Control Plane |

- Nenhuma chave tem valor padrão; **fail-closed**: sem chave configurada,
  rotas autenticadas respondem 503 (testado).
- Comparação de chaves em tempo constante (`secrets.compare_digest`).
- `/api/v1/meta/config` expõe apenas booleanos `*_configured` — testado para
  não vazar segredos.
- O cliente HTTP da Vast.ai nunca registra o header `Authorization`.
- `.env` está no `.gitignore`; só `.env.example` é versionado.

## Autorização

- Toda rota da API v1 exige `X-API-Key` (ou `Authorization: Bearer`).
- Papéis: `client` (leitura/geração) e `admin` (start/stop/destroy — §9).
- 401 para chave ausente/inválida; 403 para papel insuficiente.

## Proteções de operação financeira

1. Portão global de mutações (`LV_VAST_ENABLE_MUTATIONS=false` por padrão).
2. Autenticação admin + `confirm_cost: true` explícito.
3. Verificação de orçamento antes de qualquer criação (bloqueio em 90%,
   alerta em 70%, reserva de armazenamento/tráfego).
4. `asyncio.Lock` no GPU Manager: duas solicitações simultâneas não criam
   duas instâncias (testado).
5. Idempotência local do cliente HTTP: retry de `PUT /asks/{id}` não duplica
   contratos (testado).
6. `destroy` exige confirmação explícita de persistência dos dados (§7).
7. Auditoria JSON-lines de operações admin/financeiras, com blindagem de
   campos sensíveis.

## Limites HTTP

- Rate limiting: 60 req/min + burst (janela deslizante; 429 com Retry-After).
- Corpo máximo: 10 MB (`LV_MAX_REQUEST_BODY_BYTES`).
- CORS restrito a origens configuradas (desktop dev localhost; produção explícita).
- Validação de todas as entradas por Pydantic (contratos rígidos).

## Proteção contra comandos arbitrários

O cliente **não** envia comandos shell/SSH para o worker. A criação de
instância usa campos restritos (`image`, `env` como dict tipado, `args` como
lista tipada) validados por Pydantic — sem passagem livre de comandos. A
comunicação Control Plane ↔ Worker será autenticada na Fase 2 (mTLS/token
efêmero) quando o worker existir.

## HTTPS

Em produção o Control Plane deve ser publicado atrás de TLS obrigatório
(terminação no proxy reverso com HSTS). No preview de desenvolvimento o
 túnel já entrega HTTPS; localmente, `uvicorn` sem TLS é aceitável apenas
para desenvolvimento.

## O que NÃO é garantido

- **Limite absoluto de cobrança**: os controles internos reduzem risco, mas
  a cobrança efetiva pertence à Vast.ai. Cobranças externas/colaterais
  (armazenamento após queda, tráfego, quotas) são tratadas como
  `external_override` com aviso no Cost Manager.
- O volume persistente da Vast.ai **não substitui backup** (§5) — backup
  externo opcional chega na Fase 4.
