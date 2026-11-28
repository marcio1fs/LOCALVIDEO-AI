'use strict';

/**
 * Api — cliente REST da CRM.
 * A base pode ser configurada em Configurações; por padrão usa a API local.
 * Em produção, aponte para a URL onde os webhooks/API do n8n estão expostos.
 */

const Api = (() => {
  let BASE = window.localStorage.getItem('crm.apiBase') || '';

  async function request(method, path, data) {
    const opts = { method, headers: {} };
    if (data !== undefined) {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(data);
    }
    const res = await fetch((BASE || '') + path, opts);
    if (res.status === 204) return null;
    let json;
    try {
      json = await res.json();
    } catch {
      json = {};
    }
    if (!res.ok) {
      const msg = json.error || json.detalhe || `Erro ${res.status}`;
      throw new Error(msg);
    }
    return json;
  }

  return {
    getBase: () => BASE,
    setBase: (v) => {
      BASE = v.replace(/\/$/, '');
      window.localStorage.setItem('crm.apiBase', BASE);
    },

    getMetricas: () => request('GET', '/api/metricas'),
    getConfig: () => request('GET', '/api/config'),
    getAtividades: () => request('GET', '/api/atividades'),
    getMetas: () => request('GET', '/api/metas'),
    updateMetas: (d) => request('PATCH', '/api/metas', d),

    listarNotificacoes: () => request('GET', '/api/notificacoes'),
    lerNotificacao: (id) => request('POST', `/api/notificacoes/${id}/ler`),
    lerTodasNotificacoes: () => request('POST', '/api/notificacoes/ler-todas'),

    listarClientes: (params = {}) => {
      const qs = new URLSearchParams(params).toString();
      return request('GET', '/api/clientes' + (qs ? `?${qs}` : ''));
    },
    getCliente: (id) => request('GET', `/api/clientes/${id}`),
    criarCliente: (d) => request('POST', '/api/clientes', d),
    atualizarCliente: (id, d) => request('PATCH', `/api/clientes/${id}`, d),
    deletarCliente: (id) => request('DELETE', `/api/clientes/${id}`),

    listarAtendimentos: (params = {}) => {
      const qs = new URLSearchParams(params).toString();
      return request('GET', '/api/atendimentos' + (qs ? `?${qs}` : ''));
    },
    getAtendimento: (id) => request('GET', `/api/atendimentos/${id}`),
    criarAtendimento: (d) => request('POST', '/api/atendimentos', d),
    atualizarAtendimento: (id, d) => request('PATCH', `/api/atendimentos/${id}`, d),
    addMensagem: (id, texto, autor) =>
      request('POST', `/api/atendimentos/${id}/mensagens`, { texto, autor }),
    deletarAtendimento: (id) => request('DELETE', `/api/atendimentos/${id}`),

    listarTarefas: (params = {}) => {
      const qs = new URLSearchParams(params).toString();
      return request('GET', '/api/tarefas' + (qs ? `?${qs}` : ''));
    },
    criarTarefa: (d) => request('POST', '/api/tarefas', d),
    atualizarTarefa: (id, d) => request('PATCH', `/api/tarefas/${id}`, d),
    deletarTarefa: (id) => request('DELETE', `/api/tarefas/${id}`),

    reseed: () => request('POST', '/api/seed'),
    resetar: () => request('POST', '/api/reset'),
  };
})();
