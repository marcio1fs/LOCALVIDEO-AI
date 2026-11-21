# Painel Web do Control Plane — antecipação da Fase 5 (§11)

O painel completo que seria construído com Tauri 2/React na Fase 5 está
antecipado como **aplicação web servida pelo próprio Control Plane**, em
HTML/CSS/JS vanilla (sem build, sem node_modules). O app desktop Tauri
continuará na Fase 5 — esta versão web funciona em qualquer navegador e já
cobra todos os requisitos do §11 da interface.

## Acesso

- Painel: `/` (raiz do Control Plane)
- Documentação da API: `/docs`
- Ativos estáticos: `/static/app.js`, `/static/style.css`

Conecte-se no topo com a chave de API (`X-API-Key`):
- chave **client** — leitura (status, ofertas, estimativas, histórico);
- chave **admin** — operações que geram cobrança (iniciar/encerrar sessão,
  salvar orçamento).

A chave fica apenas em memória no navegador e é enviada exclusivamente ao
Control Plane.

## Cobertura do §11

| Requisito | Onde no painel |
|---|---|
| Estado da GPU | Card "GPU Cloud" (badge da máquina de estados + spinner em estados transitórios) |
| Botão iniciar sessão | `POST /gpu/start` após **modal de confirmação de custo** (estimativa real antes de qualquer cobrança) |
| Botão encerrar sessão | Modal com STOP vs DESTROY; destroy exige checkbox de persistência (§7) |
| Provedor / Modelo GPU / VRAM | Cards de status (`GET /gpu/status`) |
| Estado do volume + espaço | Card "Armazenamento persistente" (`GET /storage/status`), barra de uso, host físico, `/data` |
| Tempo de sessão / custo da sessão | Acúmulo estimado em BRL atualizado por polling |
| Custo estimado | Botão "Estimar custo" (`GET /gpu/cost-estimate`) |
| Custo mensal | Card "Orçamento" (comprometido, externas, restante, estado) |
| Fila de geração | Card GPU (`queue_size / max`) — Job Manager chega na Fase 3 |
| Histórico de sessões | Transições de estado (`GET /gpu/usage`) em tempo real |
| Histórico de custos | Lançamentos do ledger (reservas, liquidações, cobranças externas) |
| **Orçamento configurável** | `PATCH /api/v1/gpu/budget` (admin) — limite mensal + taxa USD→BRL, persistido em `data/cost_settings.json` e auditado |
| Perfil de hardware editável | Seção "Perfil de hardware" — GPUs permitidas, VRAM/RAM/disco mínimos, confiabilidade, preço máx., horas estimadas (usado em start/ofertas) |
| Ofertas compatíveis | `POST /gpu/offers` — tabela das melhores ofertas + motivos de rejeição |

## Alertas claros (§11)

Banner no topo, derivado do estado real:

- **GPU inicializando** (STARTING/PROVISIONING/CHECKING) — aviso de que READY
  só ocorre após validação real do worker;
- **GPU pronta** (READY);
- **Volume indisponível** (VOLUME_UNAVAILABLE) — com nota de dados preservados;
- **Host indisponível** (HOST_UNAVAILABLE);
- **Orçamento próximo do limite** (ALERT_70 / BLOCK_90 / LIMIT_REACHED) + avisos
  do Cost Manager (incluindo cobranças externas);
- **Falha de geração / erro** (ERROR) com a mensagem do GPU Manager;
- Chave Vast.ai ausente e mutações desabilitadas (Fase 1: nada gera cobrança
  sem configuração explícita).

"Arquivo não puder ser salvo" chega com o pipeline de geração (Fase 3).

## Notas técnicas

- Polling adaptativo: 2 s em estados transitórios, 5 s normal; pausa com a aba
  oculta. Rate limit do servidor elevado para 120 req/min + burst 30.
- URLs relativas em todas as chamadas — compatível com o proxy do preview e
  com produção atrás de TLS.
- Envelope de erro estável (`{"error": {"code", "message"}}`) exibido nos
  modais e mensagens.
- Nenhum segredo na página pública; `meta/config` só expõe booleanos.
