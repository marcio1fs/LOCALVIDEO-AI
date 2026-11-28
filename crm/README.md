# CRM de Atendimento ao Cliente · n8n

CRM de atendimento ao cliente com **design moderno e profissional**, cuja autonomia
(roteamento de leads, SLA, follow-ups e notificações) é feita por **fluxos n8n**.

O projeto é composto por:

1. **Frontend** — app web em HTML/CSS/JS (sem dependências externas, funciona offline)
   com Dashboard, Clientes, Atendimentos, Tarefas, Relatórios e Configurações.
2. **Backend local** — servidor Node (sem dependências) que serve o frontend, a API REST
   e **emular os webhooks do n8n**, de modo que o CRM funciona completo localmente.
3. **Fluxos n8n** — 6 workflows importáveis que implementam a automação real.
4. **Docker Compose** — para subir o CRM + n8n + Postgres em produção.

---

## 🚀 Executando localmente (sem Docker)

Pré-requisito: **Node.js ≥ 18**.

```bash
cd crm
npm install        # não há dependências, mas mantém o fluxo padrão
npm run dev
```

Abra **http://localhost:4000**.

Na primeira inicialização o servidor cria automaticamente **dados de exemplo**
(clientes, atendimentos e tarefas). Os dados são persistidos em `server/data.json`.

### Rotas disponíveis

| Serviço | URL |
| --- | --- |
| Frontend | `http://localhost:4000` |
| API REST | `http://localhost:4000/api` |
| Webhooks n8n (emulados) | `http://localhost:4000/webhooks/*` |

### Endpoints REST

| Método | Rota | Descrição |
| --- | --- | --- |
| GET | `/api/metricas` | Métricas do dashboard |
| GET | `/api/atividades` | Atividades recentes |
| GET | `/api/clientes` | Lista clientes (`?q=`, `?status=`, `?tag=`) |
| POST | `/api/clientes` | Criar cliente |
| PATCH | `/api/clientes/:id` | Atualizar cliente |
| DELETE | `/api/clientes/:id` | Excluir cliente |
| GET | `/api/atendimentos` | Lista atendimentos (`?status=`, `?canal=`, `?clienteId=`) |
| POST | `/api/atendimentos` | Abrir atendimento |
| PATCH | `/api/atendimentos/:id` | Atualizar status |
| POST | `/api/atendimentos/:id/mensagens` | Adicionar mensagem |
| GET/POST | `/api/tarefas` | Listar/criar tarefas |
| PATCH/DELETE | `/api/tarefas/:id` | Atualizar/excluir tarefa |
| GET/PATCH | `/api/metas` | Metas (SLA, pontuação de leads) |
| POST | `/api/seed` | Recarregar dados de exemplo |
| POST | `/api/reset` | Limpar todos os dados |

### Webhooks (emulação n8n)

Espelham o comportamento dos workflows n8n, ideal para testar a integração sem
uma instância n8n rodando:

```bash
curl -X POST http://localhost:4000/webhooks/novo-atendimento \
  -H 'Content-Type: application/json' \
  -d '{"clienteNome":"Teste","assunto":"Validação","canal":"chat"}'

curl -X POST http://localhost:4000/webhooks/lead \
  -H 'Content-Type: application/json' \
  -d '{"nome":"Lead","email":"lead@teste.com","telefone":"(73) 9000-0000"}'
```

Aceitos: `novo-atendimento`, `interacao`, `lead`, `follow-up`, `sla`.

## ✉️ Notificações por e-mail

O CRM gera **notificações no app** (sinal de sino na topbar) e, quando configurado,
**envia e-mail real** via nodemailer. A cada novo atendimento, novo cliente/lead e
alerta de SLA é registrada uma notificação (in-app) e disparado o e-mail.

Configure o SMTP via variáveis de ambiente (no `.env` ou no `docker-compose`):

```bash
SMTP_HOST=smtp.seu-provedor.com
SMTP_PORT=587
SMTP_USER=voce@empresa.com
SMTP_PASS=sua-senha
SMTP_FROM=CRM Atendimento <crm@empresa.com>
```

Se o `SMTP_HOST` **não** estiver definido, o CRM fica em **modo dev**: registra a
notificação no app e imprime o e-mail no console (sem enviar).

Endpoints de notificações:

| Método | Rota | Descrição |
| --- | --- | --- |
| GET | `/api/notificacoes` | Lista notificações (mais recentes primeiro) |
| POST | `/api/notificacoes/:id/ler` | Marcar uma como lida |
| POST | `/api/notificacoes/ler-todas` | Marcar todas como lidas |

---

## 🐳 Executando com Docker

```bash
cd crm
cp .env.example .env      # ajuste as chaves
docker compose up -d --build
```

- CRM: **http://localhost:4000**
- n8n: **http://localhost:5678**

---

## 🚀 Deploy na Vercel (para teste)

O backend está preparado para rodar como **serverless** na Vercel, com a mesma
lógica do servidor local (handler compartilhado em `lib/`). Para persistência na
Vercel (o `data.json` não sobrevive em serverless), use **Vercel KV**.

### 1. Conectar o storage (Vercel KV)
No dashboard da Vercel: **Storage → Create → KV**. Depois, em
**Project Settings → Variables**, adicione (valores do KV dashboard):

```
KV_URL=https://xxx.kv.vercel-release.com
KV_REST_API_TOKEN=<token>
KV_NAMESPACE_ID=<namespace>
```

### 2. Definir as variáveis de ambiente
Em **Project Settings → Variables**, adicione:

```
N8N_BASE_URL=https://mastercrm.app.n8n.cloud   (se quiser disparar automações)
N8N_API_KEY=<sua chave>                         (opcional, para importar fluxos)
SMTP_HOST=... SMTP_PORT=587 SMTP_USER=... SMTP_PASS=...  (se quiser e-mail real)
```

### 3. Precisão no primeiro deploy
Se o storage KV estiver vazio, o CRM não tem dados. Para carregar os dados de
exemplo, chame uma vez após o deploy:

```bash
curl -X POST https://sua-app.vercel.app/api/seed
```

### 4. Importar os fluxos n8n
Veja a seção abaixo (ou use o script `scripts/import-n8n.mjs` com a `N8N_API_KEY`).

### 5. Webhooks na Vercel
Na Vercel, os webhooks do n8n são recebidos sob `/api/webhook/...`:

```
POST https://sua-app.vercel.app/api/webhook/novo-atendimento
POST https://sua-app.vercel.app/api/webhook/lead
POST https://sua-app.vercel.app/api/webhook/interacao
POST https://sua-app.vercel.app/api/webhook/follow-up
POST https://sua-app.vercel.app/api/webhook/sla
```

Configure esses URLs nos **Webhook nodes** dos fluxos n8n importados. Como a
instância agora é pública, a n8n Cloud pode chamar a API do CRM de volta
(callback dos fluxos) normalmente.

### 6. Substituir a URL de callback nos fluxos
Os fluxos já vêm com uma URL de callback placeholder (`https://seu-app.vercel.app`).
Depois do deploy, substitua pela sua URL real em cada nó **HTTP Request** que
faz callback no CRM:

- Em **Settings → Variables** da Vercel, você pode criar uma variável
  `CRM_URL=https://sua-app.vercel.app` (opcional).
- Ou edite diretamente os nós dos fluxos, trocando `https://seu-app.vercel.app`
  pelo endereço final do seu deploy.

### 7. Domínio personalizado e cache
- **Domínio personalizado**: em **Project Settings → Domains**, adicione seu
  domínio. A configuração (rewrites/headers) funciona automaticamente.
- **Cache de assets**: o `vercel.json` já define cache longo para `assets/`,
  cache de 1h com `stale-while-revalidate` para `css/` e `js/`, e `no-store`
  para `/api/` — o frontend carrega rápido sem travar atualizações.

---

## ⚙️ Importando os fluxos n8n

1. Abra **http://localhost:5678** e conclua a configuração inicial.
2. Em **Workflows → Import from File**, importe os arquivos de `crm/n8n/workflows/`:
   - `01-novo-atendimento.json`
   - `02-registrar-interacao.json`
   - `03-lead-routing.json`
   - `04-lembrete-follow-up.json`
   - `05-sla-monitor.json`
   - `06-relatorio-diario.json`
3. **Ative** os fluxos que desejar.
4. Configure as credenciais dos nós **HTTP Request** (Slack/e-mail) e os nós
   **HTTP Request** que acessam a API do CRM (URL `http://crm:4000` no Docker, ou
   `http://localhost:4000` em ambiente local).
5. Ajuste o caminho dos webhooks (`Webhook` nodes) para os que o CRM usa, e configure
   a **URL base da API** em *Configurações → Integração n8n* no próprio CRM.

### O que cada fluxo faz

| Fluxo | Função |
| --- | --- |
| **Novo Atendimento** | Roteia o atendimento para um atendente, calcula o SLA por canal, notifica a equipe e responde ao webhook. |
| **Registrar Interação** | Registra a mensagem e sinaliza se o SLA está em atraso. |
| **Roteamento de Leads** | Pontua o lead, classifica (VIP/médio) e cadastra no CRM. |
| **Lembrete Follow-up** | Agendado diariamente: identifica atendimentos sem resposta e cria tarefas. |
| **Monitoramento de SLA** | Agendado a cada 15 min: detecta atendimentos em atraso e emite alerta. |
| **Relatório Diário** | Agendado diariamente: monta e envia resumo por e-mail. |
| **Sincronização WhatsApp** | Recebe mensagem do Twilio/WhatsApp, abre o atendimento no CRM e responde automaticamente. |
| **Sincronização Telegram** | Gatilho de bot do Telegram: abre atendimento no CRM e envia resposta. |

## ☁️ Integração com n8n Cloud (`mastercrm.app.n8n.cloud`)

Para rodar as automações na sua instância n8n Cloud real (em vez da emulação local):

### 1. Obter a chave de API do n8n
Na instância `https://mastercrm.app.n8n.cloud`: **Settings → API → Create API key**.
Copie a chave — você usará ela no script de importação.

### 2. Importar os fluxos automaticamente
Com o repositório em mãos, rode o script de importação (ele usa a API do n8n):

```bash
cd crm
N8N_API_KEY=sua-chave-api \
N8N_BASE_URL=https://mastercrm.app.n8n.cloud \
node scripts/import-n8n.mjs
```

- Para apenas validar a chave sem importar: adicione `--dry-run`.
- O script cria os 8 fluxos na sua instância com `active: false`.

### 3. Conectar o CRM à n8n (envio de eventos)
Defina `N8N_BASE_URL` no ambiente do CRM (no `.env` ou no `docker-compose`). Quando
definida, o CRM repassa automaticamente os eventos para os webhooks da n8n:

| Evento no CRM | Webhook n8n |
| --- | --- |
| Novo cliente | `POST https://mastercrm.app.n8n.cloud/webhook/lead` |
| Novo atendimento | `POST .../webhook/novo-atendimento` |
| Mensagem enviada | `POST .../webhook/interacao` |
| Nova tarefa | `POST .../webhook/follow-up` |

```bash
N8N_BASE_URL=https://mastercrm.app.n8n.cloud
```

### 4. Configurar os fluxos importados
Em cada fluxo na sua instância n8n:
- **Ative** o fluxo.
- Configure as **credenciais** dos nós HTTP Request (Slack/e-mail/Twilio/Telegram).
- Nos nós **HTTP Request** que fazem *callback* no CRM (ex.: "Cadastrar no CRM",
  "Criar Tarefa no CRM"), aponte para a **URL pública da API do CRM**.
- **Atenção:** para que a n8n possa chamar a API do CRM de volta, o backend do CRM
  precisa estar em um endereço público (VPS, Render, Fly.io, etc.). Se o CRM rodar
  apenas localmente, as automações que *escrevem* dados no CRM não funcionarão —
  mas as de *notificação* (Slack/e-mail) funcionam normalmente.

### 5. Servidor MCP do n8n
A instância também expõe um servidor MCP em
`https://mastercrm.app.n8n.cloud/mcp-server/http`, que permite a agentes de IA
gerenciarem fluxos. Para usá-lo, conecte-o a um cliente MCP compatível (o token de
autenticação é o mesmo da API do n8n).

---

## 🎨 Personalização

- **Cores/tema**: edite as variáveis CSS no topo de `frontend/css/styles.css`.
  Tema escuro já está implementado (botão em *Configurações*).
- **SLA / pontuação**: em *Configurações → Metas de atendimento*.
- **Atendentes**: edite a fila no nó **Code** dos fluxos n8n.
- **Notificações**: troque os webhooks Slack ou use nó **Email**.

## 📁 Estrutura

```
crm/
├── vercel.json               # config de deploy Vercel (rewrites)
├── Dockerfile
├── docker-compose.yml
├── package.json
├── lib/                      # lógica compartilhada (local + Vercel)
│   ├── handler.js            # roteamento de requisições (API + webhooks + estáticos)
│   ├── store.js              # persistência (arquivo local / Vercel KV)
│   ├── notify.js             # notificações por e-mail
│   └── seed.js               # dados de exemplo
├── api/[...path].js          # função serverless da Vercel
├── server/
│   └── server.js             # servidor local (usa lib/handler.js)
├── scripts/
│   └── import-n8n.mjs        # script para importar fluxos na n8n
├── n8n/
│   └── workflows/            # fluxos n8n importáveis
└── frontend/
    ├── index.html
    ├── css/styles.css
    ├── assets/logo.svg
    └── js/ (api.js, app.js)
```

## 🛠️ Stack

- **Frontend:** HTML, CSS, JavaScript vanilla (sem build, sem dependências).
- **Backend local:** Node.js (`http` nativo).
- **Automação:** n8n (workflows importáveis).
- **Produção:** Docker / Docker Compose.
