'use strict';

/* ============================================================
   CRM Atendimento — aplicação (router, telas, interações)
   ============================================================ */

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

const esc = (s) =>
  String(s ?? '').replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])
  );

const STATUS = {
  ativo: { label: 'Ativo', cls: 'b-ativo' },
  potencial: { label: 'Potencial', cls: 'b-potencial' },
  inativo: { label: 'Inativo', cls: 'b-inativo' },
};
const LIFECYCLE = {
  lead: { label: 'Lead', cls: 'b-potencial' },
  cliente: { label: 'Cliente', cls: 'b-ativo' },
  churn: { label: 'Churn', cls: 'b-inativo' },
};
const NOTIF_ICONS = {
  atendimento: { e: '💬', bg: '#e6f0ff' },
  lead: { e: '👤', bg: '#eef0fe' },
  sla: { e: '⏱', bg: '#fef3e2' },
  tarefa: { e: '✅', bg: '#e7f8f1' },
  info: { e: '🔔', bg: '#f3f4f8' },
};
const ATT_STATUS = {
  aberto: { label: 'Aberto', cls: 'b-aberto' },
  aguardando: { label: 'Aguardando', cls: 'b-aguardando' },
  resolvido: { label: 'Resolvido', cls: 'b-resolvido' },
  fechado: { label: 'Fechado', cls: 'b-fechado' },
};
const CANAIS = {
  chat: { label: 'Chat', cls: 'b-chat' },
  email: { label: 'E-mail', cls: 'b-email' },
  telefone: { label: 'Telefone', cls: 'b-telefone' },
  presencial: { label: 'Presencial', cls: 'b-presencial' },
};
const PRIO = { urgente: 'b-urgente', alta: 'b-alta', normal: 'b-normal' };

const COLORS = ['#6366f1', '#10b981', '#f59e0b', '#8b5cf6', '#0ea5e9', '#ec4899', '#14b8a6'];

const state = {
  view: 'dashboard',
  metricas: null,
  clientes: [],
  atendimentos: [],
  tarefas: [],
  atividades: [],
  metas: null,
  // atendimentos
  convAtual: null,
  filterConv: 'all',
  // clientes
  filterCliente: 'all',
  clienteDrawer: null,
  // tarefas
  filterTarefa: 'all',
};

/* ------------------------------------------------------------- toasts */
function toast(msg, kind = 'ok') {
  const wrap = $('#toastWrap');
  const el = document.createElement('div');
  el.className = `toast ${kind}`;
  el.innerHTML = `<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">${
    kind === 'err'
      ? '<circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>'
      : '<path d="M20 6L9 17l-5-5"/>'
  }</svg><span>${esc(msg)}</span>`;
  wrap.appendChild(el);
  setTimeout(() => {
    el.style.opacity = '0';
    el.style.transform = 'translateX(30px)';
    el.style.transition = 'all .25s';
    setTimeout(() => el.remove(), 250);
  }, 2600);
}

/* ------------------------------------------------------------- modal */
function openModal(title, bodyHtml) {
  $('#modalTitle').textContent = title;
  $('#modalBody').innerHTML = bodyHtml;
  const ov = $('#modalOverlay');
  ov.hidden = false;
  ov.style.display = 'grid';
}
function closeModal() {
  const ov = $('#modalOverlay');
  ov.hidden = true;
  ov.style.display = 'none';
  $('#modalBody').innerHTML = '';
}

/* ------------------------------------------------------------- drawer */
function openDrawer(html) {
  let ov = $('#drawerOverlay');
  if (!ov) {
    ov = document.createElement('div');
    ov.id = 'drawerOverlay';
    ov.className = 'drawer-overlay';
    ov.addEventListener('click', (e) => {
      if (e.target === ov) closeDrawer();
    });
    document.body.appendChild(ov);
  }
  ov.innerHTML = `<div class="drawer">${html}</div>`;
  ov.hidden = false;
}
function closeDrawer() {
  const ov = $('#drawerOverlay');
  if (ov) {
    ov.hidden = true;
    ov.innerHTML = '';
  }
}

/* ------------------------------------------------------------- notificações */
let notifsCache = [];
async function refreshNotifs() {
  try {
    notifsCache = await Api.listarNotificacoes();
    updateNotifBadge();
    if (!$('#notifPanel').hidden) renderNotifPanel();
  } catch (e) { /* ignora */ }
}
function updateNotifBadge() {
  const n = notifsCache.filter((x) => !x.lido).length;
  const badge = $('#notifBadge');
  if (n > 0) {
    badge.hidden = false;
    badge.textContent = n > 9 ? '9+' : String(n);
  } else {
    badge.hidden = true;
  }
}
function renderNotifPanel() {
  const list = $('#notifList');
  if (!notifsCache.length) {
    list.innerHTML = `<div class="empty-state" style="padding:30px 16px"><strong>Sem notificações</strong>Você sera avisado de novos eventos.</div>`;
    return;
  }
  list.innerHTML = notifsCache
    .map((n) => {
      const ic = NOTIF_ICONS[n.tipo] || NOTIF_ICONS.info;
      return `<div class="notif-item ${n.lido ? '' : 'unread'}" data-notif="${n.id}">
        <div class="notif-icon" style="background:${ic.bg}">${ic.e}</div>
        <div class="notif-body">
          <div class="notif-title">${esc(n.titulo)}</div>
          <div class="notif-desc">${esc(n.descricao).replace(/\n/g, '<br>')}</div>
          <div class="notif-time">${relativeTime(n.criadoEm)}</div>
        </div>
      </div>`;
    })
    .join('');
}
function openNotifPanel() {
  const panel = $('#notifPanel');
  panel.hidden = false;
  panel.style.display = 'block';
  renderNotifPanel();
}
function closeNotifPanel() {
  const panel = $('#notifPanel');
  panel.hidden = true;
  panel.style.display = 'none';
}

/* ------------------------------------------------------------- helpers de render */
function initials(name) {
  return (name || '?')
    .split(' ')
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0])
    .join('')
    .toUpperCase();
}
function fmtDate(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  return d.toLocaleDateString('pt-BR', { day: '2-digit', month: 'short' });
}
function fmtTime(iso) {
  if (!iso) return '';
  return new Date(iso).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
}
function fmtDateTime(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleString('pt-BR', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });
}
function relativeTime(iso) {
  if (!iso) return '—';
  const diff = Date.now() - new Date(iso).getTime();
  const min = Math.round(diff / 60000);
  if (min < 1) return 'agora';
  if (min < 60) return `${min} min`;
  const h = Math.round(min / 60);
  if (h < 24) return `${h} h`;
  const d = Math.round(h / 24);
  if (d < 7) return `${d} d`;
  return fmtDate(iso);
}

/* ------------------------------------------------------------- GRÁFICOS */
function donutChart(data, size = 150) {
  const total = data.reduce((s, d) => s + d.value, 0) || 1;
  const r = size / 2 - 14;
  const cx = size / 2, cy = size / 2;
  const C = 2 * Math.PI * r;
  let offset = 0;
  const segs = data.map((d, i) => {
    const frac = d.value / total;
    const len = frac * C;
    const seg = `<circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="${d.color}" stroke-width="16"
      stroke-dasharray="${len} ${C - len}" stroke-dashoffset="${-offset}" transform="rotate(-90 ${cx} ${cy})"/>`;
    offset += len;
    return seg;
  }).join('');
  return `<svg viewBox="0 0 ${size} ${size}" width="${size}" height="${size}">
    <circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="var(--border)" stroke-width="16"/>
    ${segs}
    <text x="${cx}" y="${cy - 2}" text-anchor="middle" font-size="22" font-weight="700" fill="var(--text)">${total}</text>
    <text x="${cx}" y="${cy + 16}" text-anchor="middle" font-size="10" fill="var(--text-mute)">total</text>
  </svg>`;
}

function barChart(data) {
  const max = Math.max(1, ...data.map((d) => d.value));
  return `<div class="chart-bars">${data
    .map(
      (d) => `<div class="chart-bar-col">
        <div class="chart-bar-val">${d.value}</div>
        <div class="chart-bar" style="height:${(d.value / max) * 100}%"></div>
        <div class="chart-bar-label">${esc(d.label)}</div>
      </div>`
    )
    .join('')}</div>`;
}

/* ============================================================ VISUALIZAÇÕES */
const views = {};

/* ---------------------------------------------------------- DASHBOARD */
views.dashboard = async () => {
  const m = state.metricas || (await Api.getMetricas());
  const acts = (state.atividades.length ? state.atividades : await Api.getAtividades()).slice(0, 8);
  const convs = (state.atendimentos.length ? state.atendimentos : await Api.listarAtendimentos()).slice(0, 5);

  const kpis = [
    { icon: '👥', bg: '#eef0fe', color: '#6366f1', value: m.clientes, label: 'Clientes cadastrados', trend: `${m.clientesAtivos} ativos` },
    { icon: '💬', bg: '#e6f0ff', color: '#2563eb', value: m.atendimentosAbertos, label: 'Atendimentos abertos', trend: `${m.atendimentosResolvidos} resolvidos` },
    { icon: '⏱', bg: '#fef3e2', color: '#f59e0b', value: m.emAtraso, label: 'Atraso por SLA', trend: `alvo ${m.slaMinutos} min` },
    { icon: '⭐', bg: '#e7f8f1', color: '#10b981', value: m.notaMedia || '—', label: 'Avaliação média', trend: `${m.atividadeSemana} atividades/semana` },
  ].map(
    (k) => `<div class="kpi">
      <div class="kpi-icon" style="background:${k.bg};color:${k.color};font-size:18px">${k.icon}</div>
      <div class="kpi-value">${k.value}</div>
      <div class="kpi-label">${k.label}</div>
      <div class="kpi-trend" style="color:var(--text-mute)">${k.trend}</div>
    </div>`
  ).join('');

  const activityIcons = {
    novo_cliente: { e: '👤', bg: '#eef0fe' },
    atendimento_aberto: { e: '💬', bg: '#e6f0ff' },
  };
  const actHtml = acts.length
    ? acts
        .map((a) => {
          const ic = activityIcons[a.tipo] || { e: '•', bg: '#f3f4f8' };
          return `<div class="activity-item">
            <div class="activity-dot" style="background:${ic.bg}">${ic.e}</div>
            <div>
              <div class="activity-text">${esc(a.descricao)}</div>
              <div class="activity-time">${relativeTime(a.criadoEm)}</div>
            </div>
          </div>`;
        })
        .join('')
    : `<div class="empty-state"><strong>Sem atividades recentes</strong>Comece um atendimento para gerar atividade.</div>`;

  const convRows = convs.length
    ? convs
        .map(
          (c) => `<tr class="row-click" data-conv="${c.id}">
            <td><div class="cell-user"><div class="avatar" style="background:${(c.clienteNome || '?').split('').reduce((s, ch) => s + ch.charCodeAt(0), 0) % 8 ? '#6366f1' : '#0ea5e9'}">${initials(c.clienteNome)}</div>
            <div class="meta"><strong>${esc(c.clienteNome)}</strong><small>${esc(c.assunto)}</small></div></div></td>
            <td><span class="badge ${ATT_STATUS[c.status]?.cls || 'b-aberto'}">${ATT_STATUS[c.status]?.label || c.status}</span></td>
            <td><span class="badge ${CANAIS[c.canal]?.cls || 'b-chat'} no-dot badge-no-dot">${CANAIS[c.canal]?.label || c.canal}</span></td>
            <td><small style="color:var(--text-mute)">${relativeTime(c.atualizadoEm)}</small></td>
          </tr>`
        )
        .join('')
    : `<tr><td colspan="4"><div class="empty-state">Sem atendimentos.</div></td></tr>`;

  return `
    ${kpis}
    <div class="grid-2">
      <div class="card">
        <div class="card-head"><h3>Atendimentos recentes</h3>
          <button class="btn btn-ghost btn-sm" data-nav="atendimentos">Ver todos</button></div>
        <div class="table-wrap">
          <table class="data">
            <thead><tr><th>Cliente</th><th>Status</th><th>Canal</th><th>Atualizado</th></tr></thead>
            <tbody>${convRows}</tbody>
          </table>
        </div>
      </div>
      <div class="card">
        <div class="card-head"><h3>Atividade recente</h3></div>
        <div class="card-body"><div class="activity">${actHtml}</div></div>
      </div>
    </div>
    <div class="card" style="margin-top:20px">
      <div class="card-head"><h3>Atendimentos por canal</h3></div>
      <div class="card-body">${barChart(Object.entries(m.porCanal).map(([label, value]) => ({ label: CANAIS[label]?.label || label, value })))}</div>
    </div>
  `;
};

/* ---------------------------------------------------------- CLIENTES */
views.clientes = async (query = '') => {
  let clientes = state.clientes.length ? state.clientes : await Api.listarClientes();
  if (state.filterCliente !== 'all') clientes = clientes.filter((c) => c.status === state.filterCliente);
  if (query) {
    const q = query.toLowerCase();
    clientes = clientes.filter(
      (c) => c.nome.toLowerCase().includes(q) || (c.email || '').toLowerCase().includes(q) || (c.empresa || '').toLowerCase().includes(q)
    );
  }

  const chips = [
    ['all', 'Todos'],
    ['ativo', 'Ativos'],
    ['potencial', 'Potenciais'],
    ['inativo', 'Inativos'],
  ]
    .map(
      ([k, l]) =>
        `<button class="chip ${state.filterCliente === k ? 'active' : ''}" data-filter-cliente="${k}">${l}</button>`
    )
    .join('');

  const rows = clientes.length
    ? clientes
        .map(
          (c) => `<tr class="row-click" data-cliente="${c.id}">
            <td><div class="cell-user"><div class="avatar" style="background:${c.avatarColor || '#6366f1'}">${initials(c.nome)}</div>
              <div class="meta"><strong>${esc(c.nome)}</strong><small>${esc(c.empresa || c.email || '—')}</small></div></div></td>
            <td>${c.tags?.length ? c.tags.map((t) => `<span class="tag">${esc(t)}</span>`).join(' ') : '<span style="color:var(--text-mute)">—</span>'}</td>
            <td><span class="badge ${STATUS[c.status]?.cls || 'b-inativo'}">${STATUS[c.status]?.label || c.status}</span></td>
            <td>R$ ${(c.valor || 0).toLocaleString('pt-BR')}</td>
            <td><small style="color:var(--text-mute)">${relativeTime(c.lastContact || c.criadoEm)}</small></td>
          </tr>`
        )
        .join('')
    : `<tr><td colspan="5"><div class="empty-state"><strong>Nenhum cliente encontrado</strong>Tente outro filtro ou cadastre um novo cliente.</div></td></tr>`;

  return `
    <div class="toolbar">
      <div class="filter-chips">${chips}</div>
      <div style="flex:1"></div>
      <button class="btn btn-primary" data-action="novo-cliente">
        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
        Novo cliente
      </button>
    </div>
    <div class="card">
      <div class="table-wrap">
        <table class="data">
          <thead><tr><th>Cliente</th><th>Tags</th><th>Status</th><th>Valor</th><th>Contato</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    </div>
  `;
};

/* ---------------------------------------------------------- ATENDIMENTOS */
views.atendimentos = async () => {
  const convs = state.atendimentos.length ? state.atendimentos : await Api.listarAtendimentos();
  const filtered = state.filterConv === 'all' ? convs : convs.filter((c) => c.status === state.filterConv);

  const chips = [
    ['all', 'Todos'],
    ['aberto', 'Abertos'],
    ['aguardando', 'Aguardando'],
    ['resolvido', 'Resolvidos'],
  ]
    .map(
      ([k, l]) =>
        `<button class="chip ${state.filterConv === k ? 'active' : ''}" data-filter-conv="${k}">${l}</button>`
    )
    .join('');

  const list = filtered.length
    ? filtered
        .map(
          (c) => `<div class="conv-item ${state.convAtual?.id === c.id ? 'active' : ''}" data-conv-open="${c.id}">
            <div class="conv-item-top">
              <div class="conv-item-name">${esc(c.clienteNome)}</div>
              <span class="badge ${ATT_STATUS[c.status]?.cls || 'b-aberto'}">${ATT_STATUS[c.status]?.label || c.status}</span>
            </div>
            <div class="conv-item-asunto">${esc(c.assunto)}</div>
            <div class="conv-item-meta">
              <span class="badge ${CANAIS[c.canal]?.cls || 'b-chat'} no-dot badge-no-dot">${CANAIS[c.canal]?.label || c.canal}</span>
              <span>· ${relativeTime(c.atualizadoEm)}</span>
            </div>
          </div>`
        )
        .join('')
    : `<div class="empty-state"><strong>Nenhum atendimento</strong>Abra um novo atendimento para começar.</div>`;

  const conv = state.convAtual;
  const detail = conv
    ? renderConvDetail(conv)
    : `<div class="empty-state"><svg viewBox="0 0 24 24" width="46" height="46" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
      <strong>Selecione um atendimento</strong>Escolha uma conversa da lista para ver o histórico.</div>`;

  return `
    <div class="toolbar">${chips}</div>
    <div class="split">
      <div class="card conv-list">
        <div class="card-head"><h3>Conversas</h3><span style="font-size:11px;color:var(--text-mute)">${filtered.length}</span></div>
        <div class="conv-items">${list}</div>
      </div>
      <div class="card conv-view">${detail}</div>
    </div>
  `;
};

function renderConvDetail(c) {
  const msgs = c.mensagens || [];
  const thread = msgs.length
    ? msgs
        .map((m) => {
          if (m.autor === 'sistema')
            return `<div class="msg msg-sistema"><div class="bubble">${esc(m.texto)}</div><div class="time">${fmtTime(m.criadoEm)}</div></div>`;
          const me = m.autor === 'atendente';
          return `<div class="msg ${me ? 'msg-me' : 'msg-client'}">
            <div class="bubble">${esc(m.texto)}</div>
            <div class="time">${fmtTime(m.criadoEm)}</div>
          </div>`;
        })
        .join('')
    : `<div class="empty-state">Nenhuma mensagem.</div>`;

  const slaAlert = new Date(c.slaDue) < new Date() && (c.status === 'aberto' || c.status === 'aguardando');
  return `
    <div class="conv-header">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:12px">
        <div>
          <h3>${esc(c.clienteNome)}</h3>
          <div class="sub">${esc(c.assunto)} · atendente: ${esc(c.atendente)}</div>
        </div>
        <span class="badge ${ATT_STATUS[c.status]?.cls || 'b-aberto'}">${ATT_STATUS[c.status]?.label || c.status}</span>
      </div>
      <div class="conv-actions">
        <span class="badge ${CANAIS[c.canal]?.cls || 'b-chat'} no-dot badge-no-dot">${CANAIS[c.canal]?.label || c.canal}</span>
        <span style="font-size:11.5px;color:var(--text-mute);align-self:center">SLA: ${fmtDateTime(c.slaDue)}</span>
        ${slaAlert ? '<span class="badge b-urgente">em atraso</span>' : ''}
        <div style="flex:1"></div>
        <select class="chip" data-conv-status="${c.id}">
          ${Object.entries(ATT_STATUS).map(([k, v]) => `<option value="${k}" ${c.status === k ? 'selected' : ''}>${v.label}</option>`).join('')}
        </select>
      </div>
    </div>
    <div class="thread" id="thread">${thread}</div>
    <div class="composer">
      <textarea id="composerText" placeholder="Escreva uma resposta… (Enter para enviar)"></textarea>
      <button class="btn btn-primary" data-action="send-msg" data-id="${c.id}">
        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
        Enviar
      </button>
    </div>
  `;
}

/* ---------------------------------------------------------- TAREFAS */
views.tarefas = async () => {
  const tarefas = state.tarefas.length ? state.tarefas : await Api.listarTarefas();
  const filtered = state.filterTarefa === 'all' ? tarefas : tarefas.filter((t) => t.status === state.filterTarefa);

  const chips = [
    ['all', 'Todas'],
    ['aberto', 'Abertas'],
    ['concluido', 'Concluídas'],
  ]
    .map(
      ([k, l]) =>
        `<button class="chip ${state.filterTarefa === k ? 'active' : ''}" data-filter-tarefa="${k}">${l}</button>`
    )
    .join('');

  const items = filtered.length
    ? filtered
        .map(
          (t) => `<div class="task-item">
            <button class="task-check ${t.status === 'concluido' ? 'done' : ''}" data-task-toggle="${t.id}">
              ${t.status === 'concluido' ? '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>' : ''}
            </button>
            <div class="task-body">
              <div class="task-title ${t.status === 'concluido' ? 'done' : ''}">${esc(t.titulo)}</div>
              <div class="task-meta">
                ${t.clienteId ? `<span>· ${esc((state.clientes.find((c) => c.id === t.clienteId) || {}).nome || 'Cliente')}</span>` : ''}
                <span>· ${esc(t.tipo)}</span>
                ${t.dataLimite ? `<span>· ${fmtDate(t.dataLimite)}</span>` : ''}
              </div>
            </div>
            <span class="badge ${PRIO[t.prioridade] || 'b-normal'}">${t.prioridade}</span>
          </div>`
        )
        .join('')
    : `<div class="empty-state"><strong>Nenhuma tarefa</strong>Crie tarefas de follow-up e acompanhamento.</div>`;

  return `
    <div class="toolbar">
      <div class="filter-chips">${chips}</div>
      <div style="flex:1"></div>
      <button class="btn btn-primary" data-action="nova-tarefa">
        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
        Nova tarefa
      </button>
    </div>
    <div class="card"><div class="card-body" style="padding:6px 12px">${items}</div></div>
  `;
};

/* ---------------------------------------------------------- RELATÓRIOS */
views.relatorios = async () => {
  const m = state.metricas || (await Api.getMetricas());
  const convs = state.atendimentos.length ? state.atendimentos : await Api.listarAtendimentos();
  const canais = Object.entries(m.porCanal).map(([k, v]) => ({ label: CANAIS[k]?.label || k, value: v, color: COLORS[Object.keys(m.porCanal).indexOf(k) % COLORS.length] }));
  const status = Object.entries(m.porStatus).map(([k, v]) => ({ label: ATT_STATUS[k]?.label || k, value: v, color: COLORS[Object.keys(m.porStatus).indexOf(k) % COLORS.length] }));

  const tbl = convs.length
    ? `<table class="data"><thead><tr><th>Cliente</th><th>Assunto</th><th>Canal</th><th>Status</th><th>Criado</th></tr></thead><tbody>${convs
        .map(
          (c) => `<tr><td>${esc(c.clienteNome)}</td><td>${esc(c.assunto)}</td>
            <td><span class="badge ${CANAIS[c.canal]?.cls || 'b-chat'} no-dot badge-no-dot">${CANAIS[c.canal]?.label || c.canal}</span></td>
            <td><span class="badge ${ATT_STATUS[c.status]?.cls || 'b-aberto'}">${ATT_STATUS[c.status]?.label || c.status}</span></td>
            <td><small style="color:var(--text-mute)">${fmtDate(c.criadoEm)}</small></td></tr>`
        )
        .join('')}</tbody></table>`
    : `<div class="empty-state">Sem dados.</div>`;

  return `
    <div class="kpi-grid">
      <div class="kpi"><div class="kpi-icon" style="background:#eef0fe;color:#6366f1">👥</div><div class="kpi-value">${m.clientes}</div><div class="kpi-label">Clientes</div></div>
      <div class="kpi"><div class="kpi-icon" style="background:#e6f0ff;color:#2563eb">💬</div><div class="kpi-value">${m.atendimentosAbertos}</div><div class="kpi-label">Abertos</div></div>
      <div class="kpi"><div class="kpi-icon" style="background:#e7f8f1;color:#10b981">✅</div><div class="kpi-value">${m.atendimentosResolvidos}</div><div class="kpi-label">Resolvidos</div></div>
      <div class="kpi"><div class="kpi-icon" style="background:#fef3e2;color:#f59e0b">⏱</div><div class="kpi-value">${m.emAtraso}</div><div class="kpi-label">SLA em atraso</div></div>
    </div>
    <div class="grid-2-eq">
      <div class="card">
        <div class="card-head"><h3>Atendimentos por canal</h3></div>
        <div class="card-body">${barChart(canais.map((c) => ({ label: c.label, value: c.value })))}</div>
      </div>
      <div class="card">
        <div class="card-head"><h3>Por status</h3></div>
        <div class="card-body"><div class="donut-wrap">
          ${donutChart(status)}
          <div class="legend">${status.map((s) => `<div class="legend-item"><span class="legend-dot" style="background:${s.color}"></span>${esc(s.label)}<span class="v">${s.value}</span></div>`).join('')}</div>
        </div></div>
      </div>
    </div>
    <div class="card" style="margin-top:20px">
      <div class="card-head"><h3>Histórico de atendimentos</h3></div>
      <div class="table-wrap">${tbl}</div>
    </div>
  `;
};

/* ---------------------------------------------------------- CONFIGURAÇÕES */
views.configuracoes = async () => {
  const base = Api.getBase() || 'http://localhost:4000';
  const m = state.metas || (await Api.getMetas());
  const cfg = await Api.getConfig().catch(() => ({ n8nWebhookBase: null, smtp: false }));
  // Base onde a n8n deve postar eventos no CRM: URL pública (Vercel) se definida,
  // senão a origem atual do frontend.
  const whBase = (cfg.crmUrl || base) + '/api/webhook';
  const n8nStatus = cfg.n8nWebhookBase
    ? '<span class="badge b-ativo">n8n conectado</span>'
    : '<span class="badge b-potencial">n8n local (emulação)</span>';
  return `
    <div class="grid-2">
      <div class="card">
        <div class="card-head"><h3>Integração n8n</h3><div>${n8nStatus}</div></div>
        <div class="card-body" style="display:flex;flex-direction:column;gap:16px">
          <div>
            <label style="font-size:12.5px;font-weight:600;color:var(--text-soft)">URL base da API</label>
            <input id="apiBaseInput" value="${esc(base)}" style="width:100%;margin-top:6px;padding:10px 12px;border:1px solid var(--border);border-radius:10px;background:var(--surface-2)" />
            <small style="color:var(--text-mute);font-size:12px">Local: servidor Node. Produção: endpoint dos webhooks/API do n8n.</small>
          </div>
          <div>
            <div class="section-title">Webhooks do n8n</div>
            <div class="code-block">POST ${esc(whBase)}/novo-atendimento
POST ${esc(whBase)}/interacao
POST ${esc(whBase)}/lead
POST ${esc(whBase)}/follow-up
POST ${esc(whBase)}/sla</div>
          </div>
          <div style="display:flex;gap:10px">
            <button class="btn btn-primary" data-action="salvar-base">Salvar base</button>
          </div>
        </div>
      </div>

      <div class="card">
        <div class="card-head"><h3>Metas de atendimento</h3></div>
        <div class="card-body" style="display:flex;flex-direction:column;gap:16px">
          <div class="field">
            <label>SLA de resposta (minutos)</label>
            <input id="slaInput" type="number" value="${m.slaMinutos}" min="1" />
          </div>
          <div class="config-row">
            <div class="label"><strong>Pontuação de leads</strong><small>Calcular pontuação automática de novos clientes</small></div>
            <label class="switch"><input type="checkbox" id="pontosLead" ${m.pontosLead ? 'checked' : ''} /><span class="slider"></span></label>
          </div>
          <div style="display:flex;gap:10px">
            <button class="btn btn-primary" data-action="salvar-metas">Salvar metas</button>
          </div>
        </div>
      </div>
    </div>

    <div class="card" style="margin-top:20px">
      <div class="card-head"><h3>Aparência</h3></div>
      <div class="card-body">
        <div class="config-row">
          <div class="label"><strong>Tema escuro</strong><small>Alterne entre claro e escuro</small></div>
          <label class="switch"><input type="checkbox" id="themeToggle" ${document.documentElement.dataset.theme === 'dark' ? 'checked' : ''} /><span class="slider"></span></label>
        </div>
      </div>
    </div>

    <div class="card" style="margin-top:20px">
      <div class="card-head"><h3>Dados de demonstração</h3></div>
      <div class="card-body" style="display:flex;gap:10px;flex-wrap:wrap">
        <button class="btn btn-ghost" data-action="reseed">Recarregar dados de exemplo</button>
        <button class="btn btn-danger" data-action="resetar">Limpar todos os dados</button>
        <small style="align-self:center;color:var(--text-mute)">Os dados são persistidos em server/data.json.</small>
      </div>
    </div>
  `;
};

/* ============================================================ RENDER / ROUTER */
const TITLES = {
  dashboard: ['Dashboard', 'Visão geral do atendimento ao cliente'],
  clientes: ['Clientes', 'Gerencie seu cadastro de clientes'],
  atendimentos: ['Atendimentos', 'Conversas e histórico de interações'],
  tarefas: ['Tarefas', 'Follow-ups e acompanhamentos'],
  relatorios: ['Relatórios', 'Métricas e desempenho do atendimento'],
  configuracoes: ['Configurações', 'Integração n8n, metas e aparência'],
};

async function render(view) {
  state.view = view;
  $('#pageTitle').textContent = TITLES[view][0];
  $('#pageSub').textContent = TITLES[view][1];
  $$('.nav-item').forEach((b) => b.classList.toggle('active', b.dataset.view === view));

  const fn = views[view];
  $('#content').innerHTML = '<div class="empty-state">Carregando…</div>';
  try {
    $('#content').innerHTML = await fn($('#globalSearch').value);
  } catch (err) {
    $('#content').innerHTML = `<div class="empty-state"><strong>Erro ao carregar</strong>${esc(err.message)}</div>`;
  }
}

async function navigate(view) {
  closeDrawer();
  // carrega os dados necessários antes de renderizar (evita render duplicada)
  try {
    if (view === 'dashboard' || view === 'relatorios') {
      state.metricas = await Api.getMetricas();
      if (view === 'dashboard') state.atividades = await Api.getAtividades();
    }
    if (view === 'clientes') state.clientes = await Api.listarClientes();
    if (view === 'atendimentos') {
      state.atendimentos = await Api.listarAtendimentos();
      if (!state.convAtual || !state.atendimentos.find((c) => c.id === state.convAtual.id)) {
        state.convAtual = state.atendimentos[0] || null;
      }
      if (state.convAtual) {
        state.convAtual = await Api.getAtendimento(state.convAtual.id);
      }
    }
    if (view === 'tarefas') state.tarefas = await Api.listarTarefas();
    if (view === 'configuracoes') state.metas = await Api.getMetas();
  } catch (e) {
    /* a view mostra o erro se necessário */
  }
  await render(view);
}

/* ============================================================ MODALS FORMULÁRIOS */
function clienteForm(c = {}) {
  return `<form id="clienteForm">
    <div class="form-grid">
      <div class="field"><label>Nome</label><input name="nome" required value="${esc(c.nome || '')}" /></div>
      <div class="field"><label>E-mail</label><input name="email" type="email" value="${esc(c.email || '')}" /></div>
      <div class="field"><label>Telefone</label><input name="telefone" value="${esc(c.telefone || '')}" /></div>
      <div class="field"><label>Empresa</label><input name="empresa" value="${esc(c.empresa || '')}" /></div>
      <div class="field"><label>Segmento</label><input name="segmento" value="${esc(c.segmento || '')}" placeholder="Varejo, Serviços, Corporativo…" /></div>
      <div class="field"><label>Site</label><input name="site" value="${esc(c.site || '')}" /></div>
      <div class="field"><label>Cidade</label><input name="cidade" value="${esc(c.cidade || '')}" /></div>
      <div class="field"><label>Estado</label><input name="estado" value="${esc(c.estado || '')}" /></div>
      <div class="field"><label>CPF/CNPJ</label><input name="cpf" value="${esc(c.cpf || '')}" /></div>
      <div class="field"><label>Aniversario</label><input name="aniversario" value="${esc(c.aniversario || '')}" placeholder="DD/MM" /></div>
      <div class="field"><label>Ciclo de vida</label><select name="lifecycle">
        ${Object.entries(LIFECYCLE).map(([k, v]) => `<option value="${k}" ${c.lifecycle === k ? 'selected' : ''}>${v.label}</option>`).join('')}
      </select></div>
      <div class="field"><label>Status</label><select name="status">
        ${Object.entries(STATUS).map(([k, v]) => `<option value="${k}" ${c.status === k ? 'selected' : ''}>${v.label}</option>`).join('')}
      </select></div>
      <div class="field"><label>Valor (R$)</label><input name="valor" type="number" value="${c.valor || 0}" /></div>
      <div class="field full"><label>Tags (separadas por virgula)</label><input name="tags" value="${esc((c.tags || []).join(', '))}" /></div>
      <div class="field full"><label>Observacoes</label><textarea name="observacoes">${esc(c.observacoes || '')}</textarea></div>
    </div>
    <div class="modal-actions">
      <button type="button" class="btn btn-ghost" data-close>Cancelar</button>
      <button type="submit" class="btn btn-primary">Salvar</button>
    </div>
  </form>`;
}

function atendimentoForm() {
  const opts = state.clientes.map((c) => `<option value="${c.id}">${esc(c.nome)}</option>`).join('');
  return `<form id="atendimentoForm">
    <div class="form-grid">
      <div class="field full"><label>Cliente</label><select name="clienteId" required><option value="">Selecione…</option>${opts}</select></div>
      <div class="field full"><label>Assunto</label><input name="assunto" required placeholder="Qual o motivo do atendimento?" /></div>
      <div class="field"><label>Canal</label><select name="canal">
        ${Object.entries(CANAIS).map(([k, v]) => `<option value="${k}">${v.label}</option>`).join('')}
      </select></div>
      <div class="field"><label>Atendente</label><input name="atendente" value="Ana" /></div>
    </div>
    <div class="modal-actions">
      <button type="button" class="btn btn-ghost" data-close>Cancelar</button>
      <button type="submit" class="btn btn-primary">Abrir atendimento</button>
    </div>
  </form>`;
}

function tarefaForm() {
  const opts = state.clientes.map((c) => `<option value="${c.id}">${esc(c.nome)}</option>`).join('');
  return `<form id="tarefaForm">
    <div class="form-grid">
      <div class="field full"><label>Título</label><input name="titulo" required /></div>
      <div class="field full"><label>Cliente</label><select name="clienteId"><option value="">—</option>${opts}</select></div>
      <div class="field"><label>Tipo</label><select name="tipo">
        <option value="follow-up">Follow-up</option><option value="demo">Demonstração</option>
        <option value="retenção">Retenção</option><option value="outro">Outro</option>
      </select></div>
      <div class="field"><label>Prioridade</label><select name="prioridade">
        <option value="normal">Normal</option><option value="alta">Alta</option><option value="urgente">Urgente</option>
      </select></div>
    </div>
    <div class="modal-actions">
      <button type="button" class="btn btn-ghost" data-close>Cancelar</button>
      <button type="submit" class="btn btn-primary">Criar tarefa</button>
    </div>
  </form>`;
}

/* ============================================================ EVENTOS */
async function openClienteDrawer(id) {
  const c = await Api.getCliente(id);
  const convs = await Api.listarAtendimentos({ clienteId: id });
  const tarefas = await Api.listarTarefas({ clienteId: id });
  state.clienteDrawer = c;

  const html = `
    <div class="drawer-head">
      <div class="avatar" style="width:48px;height:48px;font-size:16px;background:${c.avatarColor || '#6366f1'}">${initials(c.nome)}</div>
      <div style="flex:1">
        <h3 style="font-size:16px">${esc(c.nome)}</h3>
        <div style="font-size:12px;color:var(--text-mute);margin-top:2px">${esc(c.empresa || '—')} · ${esc(c.email || '—')}</div>
        <div style="margin-top:8px"><span class="badge ${STATUS[c.status]?.cls || 'b-inativo'}">${STATUS[c.status]?.label || c.status}</span></div>
      </div>
      <button class="icon-btn" data-close-drawer aria-label="Fechar">
        <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
      </button>
    </div>
    <div class="drawer-body">
      <div>
        <div class="section-title">Informações</div>
        <div class="detail-list">
          <div class="detail-row"><span class="k">Segmento</span><span class="v">${esc(c.segmento || '-')}</span></div>
          <div class="detail-row"><span class="k">Cidade / UF</span><span class="v">${esc([c.cidade, c.estado].filter(Boolean).join(' / ') || '-')}</span></div>
          <div class="detail-row"><span class="k">Site</span><span class="v">${esc(c.site || '-')}</span></div>
          <div class="detail-row"><span class="k">Aniversario</span><span class="v">${esc(c.aniversario || '-')}</span></div>
          <div class="detail-row"><span class="k">CPF/CNPJ</span><span class="v">${esc(c.cpf || '-')}</span></div>
          <div class="detail-row"><span class="k">Ciclo de vida</span><span class="v"><span class="badge ${LIFECYCLE[c.lifecycle]?.cls || 'b-inativo'} no-dot badge-no-dot">${LIFECYCLE[c.lifecycle]?.label || c.lifecycle || '-'}</span></span></div>
          <div class="detail-row"><span class="k">Telefone</span><span class="v">${esc(c.telefone || '-')}</span></div>
          <div class="detail-row"><span class="k">Valor</span><span class="v">R$ ${(c.valor || 0).toLocaleString('pt-BR')}</span></div>
          <div class="detail-row"><span class="k">Pontuação</span><span class="v">${c.pontos}</span></div>
          <div class="detail-row"><span class="k">Cadastrado</span><span class="v">${fmtDate(c.criadoEm)}</span></div>
          <div class="detail-row"><span class="k">Ultimo contato</span><span class="v">${relativeTime(c.lastContact)}</span></div>
        </div>
      </div>
      ${c.tags?.length ? `<div><div class="section-title">Tags</div><div style="display:flex;gap:6px;flex-wrap:wrap">${c.tags.map((t) => `<span class="tag">${esc(t)}</span>`).join('')}</div></div>` : ''}
      ${c.observacoes ? `<div><div class="section-title">Observações</div><p style="font-size:13px;color:var(--text-soft);line-height:1.5">${esc(c.observacoes)}</p></div>` : ''}
      <div>
        <div class="section-title">Atendimentos (${convs.length})</div>
        ${convs.length ? `<div style="display:flex;flex-direction:column;gap:8px">${convs.map((a) => `
          <div class="conv-item" data-conv-open="${a.id}" style="border-bottom:none;padding:10px 12px;background:var(--surface-2)">
            <div class="conv-item-top"><span class="conv-item-name" style="font-size:13px">${esc(a.assunto)}</span>
            <span class="badge ${ATT_STATUS[a.status]?.cls || 'b-aberto'}">${ATT_STATUS[a.status]?.label || a.status}</span></div>
          </div>`).join('')}</div>` : '<p style="font-size:13px;color:var(--text-mute)">Sem atendimentos.</p>'}
      </div>
      <div>
        <div class="section-title">Tarefas (${tarefas.length})</div>
        ${tarefas.length ? `<div style="display:flex;flex-direction:column;gap:8px">${tarefas.map((t) => `
          <div class="task-item" style="padding:10px 12px"><div class="task-body"><div class="task-title ${t.status === 'concluido' ? 'done' : ''}" style="font-size:13px">${esc(t.titulo)}</div></div>
          <span class="badge ${PRIO[t.prioridade] || 'b-normal'}">${t.prioridade}</span></div>`).join('')}</div>` : '<p style="font-size:13px;color:var(--text-mute)">Sem tarefas.</p>'}
      </div>
    </div>
    <div class="drawer-foot">
      <button class="btn btn-ghost" data-close-drawer>Fechar</button>
      <button class="btn btn-primary" data-action="editar-cliente" data-id="${c.id}">Editar</button>
    </div>
  `;
  openDrawer(html);
}

document.addEventListener('click', async (e) => {
  // navegação sidebar
  const nav = e.target.closest('.nav-item');
  if (nav) return navigate(nav.dataset.view);

  // botão novo atendimento
  if (e.target.closest('#novoAtendimentoBtn')) return openModal('Novo atendimento', atendimentoForm());

  // action buttons
  const action = e.target.closest('[data-action]');
  if (action) {
    const a = action.dataset.action;
    if (a === 'novo-cliente') return openModal('Novo cliente', clienteForm());
    if (a === 'nova-tarefa') return openModal('Nova tarefa', tarefaForm());
    if (a === 'editar-cliente') {
      const c = state.clienteDrawer;
      closeDrawer();
      return openModal('Editar cliente', clienteForm(c));
    }
    if (a === 'send-msg') {
      const id = action.dataset.id;
      const ta = $('#composerText');
      const texto = ta.value.trim();
      if (!texto) return;
      try {
        const atd = await Api.addMensagem(id, texto, 'atendente');
        state.convAtual = atd;
        ta.value = '';
        toast('Mensagem enviada');
        await render(state.view);
      } catch (err) {
        toast(err.message, 'err');
      }
      return;
    }
    if (a === 'salvar-base') {
      Api.setBase($('#apiBaseInput').value);
      toast('URL base salva');
      return;
    }
    if (a === 'salvar-metas') {
      try {
        const metas = await Api.updateMetas({
          slaMinutos: Number($('#slaInput').value) || 60,
          pontosLead: $('#pontosLead').checked,
        });
        state.metas = metas;
        toast('Metas salvas');
      } catch (err) {
        toast(err.message, 'err');
      }
      return;
    }
    if (a === 'reseed') {
      try {
        await Api.reseed();
        await refreshAll();
        toast('Dados de exemplo recarregados');
        navigate(state.view);
      } catch (err) {
        toast(err.message, 'err');
      }
      return;
    }
    if (a === 'resetar') {
      try {
        await Api.resetar();
        state.convAtual = null;
        await refreshAll();
        toast('Dados limpos');
        navigate('dashboard');
      } catch (err) {
        toast(err.message, 'err');
      }
      return;
    }
  }

  // filtros
  const fc = e.target.closest('[data-filter-cliente]');
  if (fc) {
    state.filterCliente = fc.dataset.filterCliente;
    return render(state.view);
  }
  const fcv = e.target.closest('[data-filter-conv]');
  if (fcv) {
    state.filterConv = fcv.dataset.filterConv;
    return render(state.view);
  }
  const ft = e.target.closest('[data-filter-tarefa]');
  if (ft) {
    state.filterTarefa = ft.dataset.filterTarefa;
    return render(state.view);
  }

  // abrir conversa (lista)
  const co = e.target.closest('[data-conv-open]');
  if (co) {
    try {
      state.convAtual = await Api.getAtendimento(co.dataset.convOpen);
      return render(state.view);
    } catch (err) {
      toast(err.message, 'err');
    }
    return;
  }

  // abrir cliente (tabela)
  const cl = e.target.closest('[data-cliente]');
  if (cl) {
    openClienteDrawer(cl.dataset.cliente);
    return;
  }

  // fechar drawer
  if (e.target.closest('[data-close-drawer]')) return closeDrawer();

  // fechar modal
  if (e.target.closest('#modalClose') || e.target.closest('[data-close]') || e.target.id === 'modalOverlay') {
    return closeModal();
  }

  // toggle tarefa
  const tt = e.target.closest('[data-task-toggle]');
  if (tt) {
    const id = tt.dataset.taskToggle;
    const t = state.tarefas.find((x) => x.id === id);
    if (t) {
      const novo = t.status === 'concluido' ? 'aberto' : 'concluido';
      try {
        const updated = await Api.atualizarTarefa(id, { status: novo });
        const idx = state.tarefas.findIndex((x) => x.id === id);
        state.tarefas[idx] = updated;
        await render(state.view);
      } catch (err) {
        toast(err.message, 'err');
      }
    }
    return;
  }

  // mudar status atendimento
  const cs = e.target.closest('[data-conv-status]');
  if (cs) {
    const id = cs.dataset.convStatus;
    const novo = cs.value;
    try {
      const updated = await Api.atualizarAtendimento(id, { status: novo });
      state.convAtual = updated;
      const idx = state.atendimentos.findIndex((x) => x.id === id);
      if (idx >= 0) state.atendimentos[idx] = updated;
      await render(state.view);
      toast('Status atualizado');
    } catch (err) {
      toast(err.message, 'err');
    }
    return;
  }

  // nav interno (ver todos)
  const nv = e.target.closest('[data-nav]');
  if (nv) return navigate(nv.dataset.nav);
});

// submits de forms (modal)
document.addEventListener('submit', async (e) => {
  if (e.target.id === 'clienteForm') {
    e.preventDefault();
    const data = Object.fromEntries(new FormData(e.target).entries());
    data.tags = (data.tags || '').split(',').map((s) => s.trim()).filter(Boolean);
    data.valor = Number(data.valor) || 0;
    try {
      if (state.clienteDrawer && e.target.querySelector('[name=nome]').value === state.clienteDrawer.nome && state.clienteDrawer.email === data.email) {
        // edição
        const updated = await Api.atualizarCliente(state.clienteDrawer.id, data);
        const idx = state.clientes.findIndex((c) => c.id === updated.id);
        if (idx >= 0) state.clientes[idx] = updated;
        toast('Cliente atualizado');
      } else {
        const c = await Api.criarCliente(data);
        state.clientes.push(c);
        toast('Cliente cadastrado');
      }
      closeModal();
      await render(state.view);
    } catch (err) {
      toast(err.message, 'err');
    }
  } else if (e.target.id === 'atendimentoForm') {
    e.preventDefault();
    const data = Object.fromEntries(new FormData(e.target).entries());
    try {
      const a = await Api.criarAtendimento(data);
      state.atendimentos.unshift(a);
      state.convAtual = a;
      closeModal();
      toast('Atendimento aberto');
      navigate('atendimentos');
    } catch (err) {
      toast(err.message, 'err');
    }
  } else if (e.target.id === 'tarefaForm') {
    e.preventDefault();
    const data = Object.fromEntries(new FormData(e.target).entries());
    if (data.clienteId === '') delete data.clienteId;
    try {
      const t = await Api.criarTarefa(data);
      state.tarefas.unshift(t);
      closeModal();
      toast('Tarefa criada');
      await render(state.view);
    } catch (err) {
      toast(err.message, 'err');
    }
  }
});

// composer Enter
document.addEventListener('keydown', (e) => {
  if (e.target.id === 'composerText' && e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    const btn = $('[data-action="send-msg"]');
    if (btn) btn.click();
  }
});

// tema
document.addEventListener('change', (e) => {
  if (e.target.id === 'themeToggle') {
    const dark = e.target.checked;
    document.documentElement.dataset.theme = dark ? 'dark' : '';
    window.localStorage.setItem('crm.theme', dark ? 'dark' : 'light');
  }
});

// busca global
let searchTimer;
document.addEventListener('input', (e) => {
  if (e.target.id !== 'globalSearch') return;
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    if (e.target.value.trim()) navigate('clientes');
  }, 250);
});

// menu mobile
document.addEventListener('click', (e) => {
  if (e.target.closest('#menuToggle')) {
    $('#sidebar').classList.toggle('open');
  }
});

// painel de notificações
document.addEventListener('click', async (e) => {
  const panel = $('#notifPanel');
  // fecha quando clica fora do sino e do painel
  if (!panel.hidden && !e.target.closest('#notifBtn') && !e.target.closest('#notifPanel')) {
    return closeNotifPanel();
  }
  // marcar todas lidas
  if (e.target.closest('#lerTodasBtn')) {
    try {
      await Api.lerTodasNotificacoes();
      await refreshNotifs();
      toast('Todas as notificações lidas');
    } catch (err) {
      toast(err.message, 'err');
    }
    return;
  }
  // abrir item -> marcar lido e navegar
  const item = e.target.closest('[data-notif]');
  if (item) {
    const id = item.dataset.notif;
    const n = notifsCache.find((x) => x.id === id);
    try {
      await Api.lerNotificacao(id);
      await refreshNotifs();
      if (n && n.clienteId) {
        closeNotifPanel();
        openClienteDrawer(n.clienteId);
      }
    } catch (err) {
      toast(err.message, 'err');
    }
  }
});

/* ============================================================ INÍCIO */
async function refreshAll() {
  try {
    state.metricas = await Api.getMetricas();
    state.clientes = await Api.listarClientes();
    state.atendimentos = await Api.listarAtendimentos();
    state.tarefas = await Api.listarTarefas();
    state.atividades = await Api.getAtividades();
    state.metas = await Api.getMetas();
    await refreshNotifs();
  } catch (e) {
    /* ok */
  }
}

async function boot() {
  // tema persistido
  if (window.localStorage.getItem('crm.theme') === 'dark') {
    document.documentElement.dataset.theme = 'dark';
  }
  await refreshAll();
  await refreshNotifs();
  navigate('dashboard');

  // toque no sino abre/fecha o painel de notificações
  $('#notifBtn').addEventListener('click', (e) => {
    e.stopPropagation();
    const panel = $('#notifPanel');
    if (panel.hidden) openNotifPanel();
    else closeNotifPanel();
  });
}

boot();
