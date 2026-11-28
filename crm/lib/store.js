'use strict';

/**
 * Store — persistência plugável para o CRM.
 *
 * - Local: grava em arquivo (server/data.json ou CRM_DATA_FILE).
 * - Vercel/serverless: usa Vercel KV se KV_URL/KV_REST_API_TOKEN/KV_NAMESPACE_ID
 *   estiverem definidos (o arquivo não persiste em serverless).
 *
 * Métodos de leitura são síncronos (a partir do state em memória); métodos de
 * gravação são assíncronos e aguardam a persistência antes de retornar.
 */

const fs = require('fs');
const path = require('path');

const DATA_FILE = process.env.CRM_DATA_FILE || path.join(__dirname, '..', 'server', 'data.json');

const KV_URL = (process.env.KV_URL || '').replace(/\/$/, '');
const KV_TOKEN = process.env.KV_REST_API_TOKEN || '';
const KV_NS = process.env.KV_NAMESPACE_ID || '';
const KV_KEY = process.env.KV_KEY || 'crm:state';
const USE_KV = KV_URL && KV_TOKEN && KV_NS;

const DEFAULTS = {
  clientes: [],
  atendimentos: [],
  tarefas: [],
  atividades: [],
  notificacoes: [],
  atendentes: [],
  metas: {
    slaMinutos: 60,
    pontosLead: true,
  },
};

let state = structuredClone(DEFAULTS);
let loadedPromise = null;

async function doLoad() {
  try {
    if (USE_KV) {
      const r = await fetch(`${KV_URL}/v3/rest/kv/${KV_NS}/${KV_KEY}`, {
        headers: { Authorization: `Bearer ${KV_TOKEN}` },
      });
      if (r.ok) {
        const data = await r.json();
        state = { ...structuredClone(DEFAULTS), ...data };
      }
    } else if (fs.existsSync(DATA_FILE)) {
      state = { ...structuredClone(DEFAULTS), ...JSON.parse(fs.readFileSync(DATA_FILE, 'utf8')) };
    }
  } catch (err) {
    console.error('[store] falha ao carregar:', err.message);
  }
}

function ensureLoaded() {
  if (!loadedPromise) loadedPromise = doLoad();
  return loadedPromise;
}

async function persist() {
  try {
    if (USE_KV) {
      const r = await fetch(`${KV_URL}/v3/rest/kv/${KV_NS}/${KV_KEY}`, {
        method: 'PUT',
        headers: { Authorization: `Bearer ${KV_TOKEN}`, 'Content-Type': 'application/json' },
        body: JSON.stringify(state),
      });
      if (!r.ok) console.error('[store] KV PUT falhou:', r.status);
    } else {
      fs.writeFileSync(DATA_FILE, JSON.stringify(state, null, 2), 'utf8');
    }
  } catch (err) {
    console.error('[store] falha ao salvar:', err.message);
  }
}

function uid(prefix = 'id') {
  return `${prefix}_${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;
}
const now = () => new Date().toISOString();

/* ---------------------------------------------------------------- clientes */
const Clientes = {
  list(filter = {}) {
    let rows = [...state.clientes];
    if (filter.q) {
      const q = filter.q.toLowerCase();
      rows = rows.filter(
        (c) =>
          c.nome.toLowerCase().includes(q) ||
          (c.email || '').toLowerCase().includes(q) ||
          (c.telefone || '').includes(q) ||
          (c.empresa || '').toLowerCase().includes(q)
      );
    }
    if (filter.status) rows = rows.filter((c) => c.status === filter.status);
    if (filter.tag) rows = rows.filter((c) => (c.tags || []).includes(filter.tag));
    return rows;
  },
  get(id) {
    return state.clientes.find((c) => c.id === id) || null;
  },
  async create(data) {
    const cliente = {
      id: uid('cli'),
      nome: data.nome || 'Cliente',
      email: data.email || '',
      telefone: data.telefone || '',
      empresa: data.empresa || '',
      segmento: data.segmento || '',
      endereco: data.endereco || '',
      cidade: data.cidade || '',
      estado: data.estado || '',
      cpf: data.cpf || '',
      site: data.site || '',
      aniversario: data.aniversario || '',
      lifecycle: data.lifecycle || 'lead',
      tags: data.tags || [],
      status: data.status || 'potencial',
      valor: Number(data.valor) || 0,
      pontos: Number(data.pontos) || 0,
      observacoes: data.observacoes || '',
      criadoEm: now(),
      atualizadoEm: now(),
      lastContact: null,
      avatarColor: pickColor(data.nome),
    };
    state.clientes.push(cliente);
    pushAtividade('novo_cliente', `Novo cliente cadastrado: ${cliente.nome}`, cliente.id);
    await persist();
    return cliente;
  },
  async update(id, data) {
    const c = this.get(id);
    if (!c) return null;
    Object.assign(c, { ...data, atualizadoEm: now() });
    await persist();
    return c;
  },
  async remove(id) {
    const before = state.clientes.length;
    state.clientes = state.clientes.filter((c) => c.id !== id);
    const changed = state.clientes.length !== before;
    if (changed) await persist();
    return changed;
  },
};

/* ------------------------------------------------------------- atendimentos */
const Atendimentos = {
  list(filter = {}) {
    let rows = [...state.atendimentos].sort((a, b) =>
      (b.atualizadoEm || '').localeCompare(a.atualizadoEm || '')
    );
    if (filter.status) rows = rows.filter((a) => a.status === filter.status);
    if (filter.canal) rows = rows.filter((a) => a.canal === filter.canal);
    if (filter.clienteId) rows = rows.filter((a) => a.clienteId === filter.clienteId);
    return rows;
  },
  get(id) {
    return state.atendimentos.find((a) => a.id === id) || null;
  },
  async create(data) {
    const cliente = Clientes.get(data.clienteId) || null;
    const atendimento = {
      id: uid('atd'),
      clienteId: data.clienteId || null,
      clienteNome: cliente ? cliente.nome : data.clienteNome || 'Cliente',
      assunto: data.assunto || 'Novo atendimento',
      status: data.status || 'aberto',
      canal: data.canal || 'chat',
      atendente: data.atendente || '—',
      slaDue: addMinutes(now(), state.metas.slaMinutos),
      criadoEm: now(),
      atualizadoEm: now(),
      mensagens: [],
    };
    atendimento.mensagens.push(mensagem('sistema', `Atendimento aberto no canal ${atendimento.canal}.`));
    state.atendimentos.push(atendimento);
    if (cliente) {
      cliente.lastContact = now();
      Clientes.update(cliente.id, { lastContact: cliente.lastContact });
    }
    pushAtividade('atendimento_aberto', `Atendimento aberto: ${atendimento.assunto}`, cliente ? cliente.id : null);
    await persist();
    return atendimento;
  },
  async update(id, data) {
    const a = this.get(id);
    if (!a) return null;
    Object.assign(a, { ...data, atualizadoEm: now() });
    await persist();
    return a;
  },
  async addMensagem(id, texto, autor) {
    const a = this.get(id);
    if (!a) return null;
    a.mensagens.push(mensagem(autor, texto));
    a.atualizadoEm = now();
    const cliente = Clientes.get(a.clienteId);
    if (cliente) {
      cliente.lastContact = now();
      Clientes.update(cliente.id, { lastContact: cliente.lastContact });
    }
    await persist();
    return a;
  },
  async remove(id) {
    const before = state.atendimentos.length;
    state.atendimentos = state.atendimentos.filter((a) => a.id !== id);
    const changed = state.atendimentos.length !== before;
    if (changed) await persist();
    return changed;
  },
};

/* ------------------------------------------------------------------- tarefas */
const Tarefas = {
  list(filter = {}) {
    let rows = [...state.tarefas];
    if (filter.status) rows = rows.filter((t) => t.status === filter.status);
    if (filter.clienteId) rows = rows.filter((t) => t.clienteId === filter.clienteId);
    return rows.sort((a, b) => (a.dataLimite || '').localeCompare(b.dataLimite || ''));
  },
  get(id) {
    return state.tarefas.find((t) => t.id === id) || null;
  },
  async create(data) {
    const tarefa = {
      id: uid('tsk'),
      titulo: data.titulo || 'Tarefa',
      descricao: data.descricao || '',
      clienteId: data.clienteId || null,
      atendimentoId: data.atendimentoId || null,
      tipo: data.tipo || 'follow-up',
      status: data.status || 'aberto',
      prioridade: data.prioridade || 'normal',
      dataLimite: data.dataLimite || null,
      criadoEm: now(),
    };
    state.tarefas.push(tarefa);
    await persist();
    return tarefa;
  },
  async update(id, data) {
    const t = this.get(id);
    if (!t) return null;
    Object.assign(t, data);
    await persist();
    return t;
  },
  async remove(id) {
    const before = state.tarefas.length;
    state.tarefas = state.tarefas.filter((t) => t.id !== id);
    const changed = state.tarefas.length !== before;
    if (changed) await persist();
    return changed;
  },
};

/* ---------------------------------------------------------------- notificacoes */
const Notificacoes = {
  list(filter = {}) {
    let rows = [...state.notificacoes];
    if (filter.naoLidas) rows = rows.filter((n) => !n.lido);
    return rows.sort((a, b) => (b.criadoEm || '').localeCompare(a.criadoEm || ''));
  },
  unread() {
    return state.notificacoes.filter((n) => !n.lido).length;
  },
  get(id) {
    return state.notificacoes.find((n) => n.id === id) || null;
  },
  async create(data) {
    const n = {
      id: uid('ntf'),
      tipo: data.tipo || 'info',
      titulo: data.titulo || 'Notificação',
      descricao: data.descricao || '',
      clienteId: data.clienteId || null,
      atendimentoId: data.atendimentoId || null,
      lido: false,
      criadoEm: now(),
    };
    state.notificacoes.unshift(n);
    if (state.notificacoes.length > 150) state.notificacoes.length = 150;
    await persist();
    return n;
  },
  async marcarLido(id) {
    const n = this.get(id);
    if (!n || n.lido) return n;
    n.lido = true;
    await persist();
    return n;
  },
  async marcarTodasLidas() {
    state.notificacoes.forEach((n) => (n.lido = true));
    await persist();
    return state.notificacoes.length;
  },
};

/* ---------------------------------------------------------------- atividades */
function pushAtividade(tipo, descricao, clienteId) {
  state.atividades.unshift({
    id: uid('act'),
    tipo,
    descricao,
    clienteId: clienteId || null,
    criadoEm: now(),
  });
  if (state.atividades.length > 200) state.atividades.length = 200;
}

/* -------------------------------------------------------------- metas / métricas */
function getMetas() {
  return state.metas;
}
async function updateMetas(patch) {
  state.metas = { ...state.metas, ...patch };
  await persist();
  return state.metas;
}

function metricas() {
  const clientes = state.clientes;
  const atendimentos = state.atendimentos;
  const abertos = atendimentos.filter((a) => a.status === 'aberto' || a.status === 'aguardando');
  const resolvidos = atendimentos.filter((a) => a.status === 'resolvido' || a.status === 'fechado');
  const emAtraso = abertos.filter((a) => new Date(a.slaDue) < new Date());
  const aval = resolvidos
    .flatMap((a) => a.mensagens.filter((m) => m.autor === 'cliente' && m.avaliacao))
    .map((m) => m.avaliacao);
  const nota = aval.length ? aval.reduce((s, n) => s + n, 0) / aval.length : 0;
  return {
    clientes: clientes.length,
    clientesAtivos: clientes.filter((c) => c.status === 'ativo').length,
    atendimentosAbertos: abertos.length,
    atendimentosResolvidos: resolvidos.length,
    emAtraso: emAtraso.length,
    notaMedia: Math.round(nota * 10) / 10,
    tarefasAbertas: state.tarefas.filter((t) => t.status === 'aberto').length,
    atividadeSemana: state.atividades.filter((a) => Date.now() - new Date(a.criadoEm) < 7 * 86400000).length,
    porCanal: groupCount(atendimentos, 'canal'),
    porStatus: groupCount(atendimentos, 'status'),
    slaMinutos: state.metas.slaMinutos,
    notificacoesNaoLidas: state.notificacoes.filter((n) => !n.lido).length,
  };
}

async function reset() {
  state = structuredClone(DEFAULTS);
  await persist();
}

/* ----------------------------------------------------------------- utilitários */
function mensagem(autor, texto, avaliacao = null) {
  return { id: uid('msg'), autor, texto, avaliacao, criadoEm: now() };
}
function addMinutes(iso, min) {
  return new Date(new Date(iso).getTime() + min * 60000).toISOString();
}
function pickColor(seed = '') {
  const palette = ['#6366f1', '#0ea5e9', '#10b981', '#f59e0b', '#ec4899', '#8b5cf6', '#ef4444', '#14b8a6'];
  let sum = 0;
  for (let i = 0; i < seed.length; i++) sum += seed.charCodeAt(i);
  return palette[sum % palette.length];
}
function groupCount(rows, key) {
  const out = {};
  for (const r of rows) out[r[key]] = (out[r[key]] || 0) + 1;
  return out;
}

module.exports = {
  ensureLoaded,
  Clientes,
  Atendimentos,
  Tarefas,
  Notificacoes,
  getMetas,
  updateMetas,
  metricas,
  reset,
  _state: () => state,
  _useKv: () => USE_KV,
};
