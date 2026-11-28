'use strict';

/**
 * Handler — roteamento de requisições do CRM.
 * Usado por:
 *   - server/server.js (servidor local, Node http)
 *   - api/[...path].js  (função serverless da Vercel)
 */

const fs = require('fs');
const path = require('path');

const store = require('./store');
const notify = require('./notify');
const { seed } = require('./seed');

const PUBLIC = path.join(__dirname, '..', 'frontend');

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.js': 'application/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.ico': 'image/x-icon',
  '.woff2': 'font/woff2',
};

const N8N_BASE_URL = (process.env.N8N_BASE_URL || '').replace(/\/$/, '');

function corsHeaders() {
  return {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET,POST,PATCH,DELETE,OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
  };
}

function send(res, status, data) {
  const body = JSON.stringify(data);
  res.writeHead(status, {
    'Content-Type': 'application/json; charset=utf-8',
    ...corsHeaders(),
  });
  res.end(body);
}

function readBody(req) {
  return new Promise((resolve) => {
    let raw = '';
    req.on('data', (c) => (raw += c));
    req.on('end', () => {
      if (!raw) return resolve({});
      try {
        resolve(JSON.parse(raw));
      } catch {
        resolve({ _raw: raw });
      }
    });
  });
}

async function forwardToN8n(webhookPath, payload) {
  if (!N8N_BASE_URL) return;
  try {
    const r = await fetch(`${N8N_BASE_URL}/webhook/${webhookPath}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {}),
    });
    console.log(`[n8n] ${webhookPath} -> HTTP ${r.status}`);
  } catch (e) {
    console.error(`[n8n] ${webhookPath} falhou:`, e.message);
  }
}

function serveBuf(res, buf, ext) {
  res.writeHead(200, { 'Content-Type': MIME[ext] || 'application/octet-stream' });
  res.end(buf);
}

function serveStatic(req, res, url) {
  let pathname = decodeURIComponent((url || '/').split('?')[0]);
  if (pathname === '/') pathname = '/index.html';
  const file = path.join(PUBLIC, path.normalize(pathname));
  if (!file.startsWith(PUBLIC)) return send(res, 403, { error: 'Forbidden' });
  fs.readFile(file, (err, buf) => {
    if (err) return send(res, 404, { error: 'Not found' });
    serveBuf(res, buf, path.extname(file));
  });
}

/* ------------------------------------------------------- roteamento de API */
async function routeApi(pathname, method, req, res, body, qs) {
  const { Clientes, Atendimentos, Tarefas } = store;
  const params = Object.fromEntries(new URLSearchParams(qs));

  /* clientes */
  if (pathname === '/api/clientes' && method === 'GET') return send(res, 200, Clientes.list(params));
  if (pathname === '/api/clientes' && method === 'POST') {
    const c = await Clientes.create(body);
    notify.notificar({ tipo: 'lead', titulo: 'Novo cliente cadastrado', descricao: `Cliente "${c.nome}" foi cadastrado (status: ${c.status}).`, clienteId: c.id, para: c.email || null });
    forwardToN8n('lead', c);
    return send(res, 201, c);
  }
  if (/^\/api\/clientes\/[^/]+$/.test(pathname)) {
    const id = pathname.split('/').pop();
    if (method === 'GET') return send(res, 200, Clientes.get(id) || {});
    if (method === 'PATCH') return send(res, 200, await Clientes.update(id, body));
    if (method === 'DELETE') return send(res, 200, { ok: await Clientes.remove(id) });
  }

  /* atendimentos */
  if (pathname === '/api/atendimentos' && method === 'GET') return send(res, 200, Atendimentos.list(params));
  if (pathname === '/api/atendimentos' && method === 'POST') {
    const atd = await Atendimentos.create(body);
    const cliente = body.clienteId ? Clientes.get(body.clienteId) : null;
    notify.notificar({ tipo: 'atendimento', titulo: 'Novo atendimento aberto', descricao: `Atendimento "${atd.assunto}" aberto para ${atd.clienteNome} (canal ${atd.canal}, atendente ${atd.atendente}).`, clienteId: atd.clienteId, atendimentoId: atd.id, para: cliente && cliente.email ? cliente.email : null });
    forwardToN8n('novo-atendimento', atd);
    return send(res, 201, atd);
  }
  if (/^\/api\/atendimentos\/[^/]+\/mensagens$/.test(pathname) && method === 'POST') {
    const id = pathname.split('/')[3];
    const atd = await Atendimentos.addMensagem(id, body.texto, body.autor || 'atendente');
    forwardToN8n('interacao', { atendimentoId: id, texto: body.texto, autor: body.autor || 'atendente' });
    return send(res, 201, atd);
  }
  if (/^\/api\/atendimentos\/[^/]+$/.test(pathname)) {
    const id = pathname.split('/').pop();
    if (method === 'GET') return send(res, 200, Atendimentos.get(id) || {});
    if (method === 'PATCH') return send(res, 200, await Atendimentos.update(id, body));
    if (method === 'DELETE') return send(res, 200, { ok: await Atendimentos.remove(id) });
  }

  /* tarefas */
  if (pathname === '/api/tarefas' && method === 'GET') return send(res, 200, Tarefas.list(params));
  if (pathname === '/api/tarefas' && method === 'POST') {
    const t = await Tarefas.create(body);
    forwardToN8n('follow-up', t);
    return send(res, 201, t);
  }
  if (/^\/api\/tarefas\/[^/]+$/.test(pathname)) {
    const id = pathname.split('/').pop();
    if (method === 'PATCH') return send(res, 200, await Tarefas.update(id, body));
    if (method === 'DELETE') return send(res, 200, { ok: await Tarefas.remove(id) });
  }

  /* atividades / métricas / metas / config / seed */
  if (pathname === '/api/atividades' && method === 'GET') return send(res, 200, store._state().atividades);
  if (pathname === '/api/metricas' && method === 'GET') return send(res, 200, store.metricas());
  if (pathname === '/api/config' && method === 'GET') {
    return send(res, 200, {
      n8nBase: N8N_BASE_URL || null,
      n8nWebhookBase: N8N_BASE_URL ? `${N8N_BASE_URL}/webhook` : null,
      smtp: !!process.env.SMTP_HOST,
    });
  }
  if (pathname === '/api/metas' && method === 'GET') return send(res, 200, store.getMetas());
  if (pathname === '/api/metas' && method === 'PATCH') return send(res, 200, await store.updateMetas(body));
  if (pathname === '/api/notificacoes' && method === 'GET') return send(res, 200, store.Notificacoes.list(params));
  if (pathname === '/api/notificacoes/ler-todas' && method === 'POST') {
    return send(res, 200, { ok: true, marcadas: await store.Notificacoes.marcarTodasLidas() });
  }
  if (/^\/api\/notificacoes\/[^/]+\/ler$/.test(pathname) && method === 'POST') {
    return send(res, 200, await store.Notificacoes.marcarLido(pathname.split('/')[3]) || {});
  }
  if (pathname === '/api/seed' && method === 'POST') {
    await store.reset();
    return send(res, 200, { ok: true, seed: await seed() });
  }
  if (pathname === '/api/reset' && method === 'POST') {
    await store.reset();
    return send(res, 200, { ok: true });
  }
  return send(res, 404, { error: 'Rota API não encontrada' });
}

/* --------------------------------------------------------- webhooks (n8n) */
async function handleWebhook(name, body, res) {
  const { Clientes, Atendimentos, Tarefas } = store;
  switch (name) {
    case '/webhook/novo-atendimento':
    case '/webhooks/novo-atendimento': {
      const atd = await Atendimentos.create({ clienteId: body.clienteId, clienteNome: body.clienteNome, assunto: body.assunto, canal: body.canal || 'chat', atendente: body.atendente || '—' });
      const clienteW = body.clienteId ? Clientes.get(body.clienteId) : null;
      notify.notificar({ tipo: 'atendimento', titulo: 'Novo atendimento (n8n)', descricao: `Fluxo n8n registrou o atendimento "${atd.assunto}" para ${atd.clienteNome}.`, clienteId: atd.clienteId, atendimentoId: atd.id, para: clienteW && clienteW.email ? clienteW.email : null });
      return send(res, 200, { ok: true, workflow: 'novo-atendimento', atendimento: atd, mensagem: 'Fluxo n8n: atendimento registrado e roteado.' });
    }
    case '/webhook/interacao':
    case '/webhooks/interacao': {
      const atd = await Atendimentos.addMensagem(body.atendimentoId, body.texto, body.autor || 'cliente');
      return send(res, 200, { ok: true, workflow: 'registrar-interacao', atendimento: atd });
    }
    case '/webhook/lead':
    case '/webhooks/lead': {
      const cliente = await Clientes.create({ nome: body.nome, email: body.email, telefone: body.telefone, empresa: body.empresa, tags: body.tags || ['novo'], status: 'potencial' });
      notify.notificar({ tipo: 'lead', titulo: 'Novo lead (n8n)', descricao: `Lead "${cliente.nome}" roteado pelo fluxo n8n.`, clienteId: cliente.id, para: cliente.email || null });
      return send(res, 200, { ok: true, workflow: 'lead-routing', cliente, pontuacao: cliente.pontos, rotado: true });
    }
    case '/webhook/follow-up':
    case '/webhooks/follow-up': {
      const tarefa = await Tarefas.create({ titulo: body.titulo, clienteId: body.clienteId, tipo: 'follow-up', prioridade: 'normal' });
      return send(res, 200, { ok: true, workflow: 'lembrete-follow-up', tarefa });
    }
    case '/webhook/sla':
    case '/webhooks/sla': {
      const lista = Atendimentos.list({ status: 'aberto' });
      const emAtraso = lista.filter((a) => new Date(a.slaDue) < new Date());
      if (emAtraso.length) {
        const detalhe = emAtraso.slice(0, 5).map((a) => `• ${a.clienteNome} — ${a.assunto}`).join('\n');
        notify.notificar({ tipo: 'sla', titulo: `SLA em atraso (${emAtraso.length})`, descricao: `${emAtraso.length} atendimento(s) em atraso:\n${detalhe}`, atendimentoId: emAtraso[0].id });
      }
      return send(res, 200, { ok: true, workflow: 'sla-monitor', emAtraso: emAtraso.length, atendimentos: emAtraso });
    }
    default:
      return send(res, 404, { error: 'Webhook não encontrado' });
  }
}

/* ------------------------------------------------------------- entrypoint */
async function handleRequest(req, res) {
  try {
    await store.ensureLoaded();
  } catch (e) {
    /* o store carrega com fallback */
  }

  const method = req.method || 'GET';
  const [pathname, qs] = (req.url || '/').split('?');

  if (method === 'OPTIONS') {
    res.writeHead(204, corsHeaders());
    return res.end();
  }

  if (pathname.startsWith('/api/')) {
    const body = method === 'POST' || method === 'PATCH' ? await readBody(req) : {};
    // webhooks podem chegar como /api/webhook/... ou /api/webhooks/... (Vercel)
    const wb = pathname.match(/^(?:\/api)?(\/webhooks?\/.+)$/);
    if (wb) {
      return handleWebhook(wb[1], body, res);
    }
    return routeApi(pathname, method, req, res, body, qs || '');
  }

  if (pathname.startsWith('/webhook/') || pathname.startsWith('/webhooks/')) {
    const body = method === 'POST' ? await readBody(req) : {};
    return handleWebhook(pathname, body, res);
  }

  if (method === 'GET') return serveStatic(req, res, req.url);
  return send(res, 404, { error: 'Not found' });
}

module.exports = { handleRequest, forwardToN8n };
