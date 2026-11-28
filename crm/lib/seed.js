'use strict';

/**
 * Seed — dados de demonstração reais (contexto BR) para o CRM.
 */

const store = require('./store');

async function seed() {
  const { Clientes, Atendimentos, Tarefas } = store;

  const baseClientes = [
    { nome: 'Maria da Silva', email: 'maria.silva@email.com', telefone: '(73) 9881-2240', empresa: 'Comércio Lopes', segmento: 'Varejo', cidade: 'Itapetinga', estado: 'BA', site: 'lopes.com.br', aniversario: '12/03', lifecycle: 'cliente', status: 'ativo', valor: 12400, tags: ['vip', 'e-commerce'], observacoes: 'Cliente fiel, compra mensal.' },
    { nome: 'João Souza', email: 'joao.souza@email.com', telefone: '(73) 9770-1182', empresa: 'Souza Comércio', segmento: 'Varejo', cidade: 'Itapetinga', estado: 'BA', site: '', aniversario: '', lifecycle: 'cliente', status: 'ativo', valor: 8200, tags: ['e-commerce'], observacoes: 'Interessado em pacote premium.' },
    { nome: 'Ana Carvalho', email: 'ana.carvalho@empresa.com', telefone: '(75) 9920-3341', empresa: 'Carvalho Ltda', segmento: 'Corporativo', cidade: 'Vitória da Conquista', estado: 'BA', site: 'carvalho.com.br', aniversario: '', lifecycle: 'lead', status: 'potencial', valor: 0, tags: ['corporativo'], observacoes: 'Pediu demonstração.' },
    { nome: 'Pedro Alves', email: 'pedro.alves@email.com', telefone: '(73) 9810-5567', empresa: '', segmento: '', cidade: 'Itabuna', estado: 'BA', site: '', aniversario: '', lifecycle: 'churn', status: 'inativo', valor: 2400, tags: [], observacoes: 'Em avaliação de cancelamento.' },
    { nome: 'Lucas Pereira', email: 'lucas.pereira@email.com', telefone: '(75) 9841-9022', empresa: 'Pereira & Irmãos', segmento: 'Corporativo', cidade: 'Salvador', estado: 'BA', site: 'pereira.com.br', aniversario: '05/08', lifecycle: 'cliente', status: 'ativo', valor: 15600, tags: ['vip', 'corporativo'], observacoes: 'Contrato anual.' },
    { nome: 'Camila Rocha', email: 'camila.rocha@email.com', telefone: '(73) 9921-7788', empresa: '', segmento: '', cidade: 'Ilhéus', estado: 'BA', site: '', aniversario: '', lifecycle: 'lead', status: 'potencial', valor: 0, tags: ['novo'], observacoes: 'Lead de campanha de Instagram.' },
    { nome: 'Rafael Dias', email: 'rafael.dias@email.com', telefone: '(75) 9760-2210', empresa: 'Dias Digital', segmento: 'Serviços', cidade: 'Vitória da Conquista', estado: 'BA', site: 'dias.digital', aniversario: '', lifecycle: 'cliente', status: 'ativo', valor: 9100, tags: ['e-commerce'], observacoes: 'Solicitou suporte técnico.' },
    { nome: 'Juliana Ferreira', email: 'juliana.f@email.com', telefone: '(73) 9888-4412', empresa: 'Ferreira Store', segmento: 'Varejo', cidade: 'Itapetinga', estado: 'BA', site: 'ferreira.store', aniversario: '22/11', lifecycle: 'cliente', status: 'ativo', valor: 6800, tags: ['e-commerce'], observacoes: 'Frequentemente em contato.' },
  ];

  const clientes = [];
  for (const c of baseClientes) {
    clientes.push(
      await Clientes.create({
        ...c,
        pontos: c.status === 'ativo' ? 80 + (clientes.length % 20) : 20 + (clientes.length % 30),
      })
    );
  }

  const [maria, joao, ana, pedro, lucas, camila, rafael, juliana] = clientes;

  const baseAtendimentos = [
    { cliente: maria, assunto: 'Dúvida sobre renovação do plano', status: 'aberto', canal: 'chat', atendente: 'Ana', msgs: [['cliente', 'Preciso saber como renovar meu plano.'], ['atendente', 'Claro! Vou verificar sua assinatura agora.']] },
    { cliente: joao, assunto: 'Quer upgrade para premium', status: 'aguardando', canal: 'email', atendente: 'Bruno', msgs: [['atendente', 'Olá, João! Vamos conversar sobre o plano premium.'], ['cliente', 'Sim, quero entender os benefícios.']] },
    { cliente: ana, assunto: 'Solicitação de demonstração', status: 'aberto', canal: 'telefone', atendente: '—', msgs: [['atendente', 'Bem-vinda! Agendo sua demonstração.']] },
    { cliente: lucas, assunto: 'Problema no acesso da equipe', status: 'aberto', canal: 'chat', atendente: 'Ana', msgs: [['cliente', 'Meus usuários não conseguem entrar.']] },
    { cliente: camila, assunto: 'Primeira compra — dúvida', status: 'resolvido', canal: 'chat', atendente: 'Bruno', msgs: [['cliente', 'É minha primeira compra, tenho dúvidas.'], ['atendente', 'Ajudo você agora.'], ['cliente', 'Obrigado, ficou claro!']] },
    { cliente: rafael, assunto: 'Erro de integração', status: 'resolvido', canal: 'email', atendente: 'Ana', msgs: [['cliente', 'A integração está falhando.'], ['atendente', 'Corrigido, teste novamente.']] },
    { cliente: juliana, assunto: 'Pedido não consta no sistema', status: 'aberto', canal: 'chat', atendente: '—', msgs: [['cliente', 'Meu pedido não aparece.']] },
  ];

  const convs = [];
  for (const a of baseAtendimentos) {
    const created = await Atendimentos.create({
      clienteId: a.cliente.id,
      clienteNome: a.cliente.nome,
      assunto: a.assunto,
      status: a.status,
      canal: a.canal,
      atendente: a.atendente,
    });
    for (const m of a.msgs) await Atendimentos.addMensagem(created.id, m[1], m[0]);
    convs.push(created);
  }

  const tarefas = [
    { titulo: 'Renovar contrato — Maria da Silva', cliente: maria, tipo: 'follow-up', status: 'aberto', prioridade: 'alta' },
    { titulo: 'Enviar demonstração — Ana Carvalho', cliente: ana, tipo: 'demo', status: 'aberto', prioridade: 'alta' },
    { titulo: 'Revisar cancelamento — Pedro Alves', cliente: pedro, tipo: 'retenção', status: 'aberto', prioridade: 'urgente' },
    { titulo: 'Retornar contato — Camila Rocha', cliente: camila, tipo: 'follow-up', status: 'concluído', prioridade: 'normal' },
  ];

  for (const t of tarefas) {
    await Tarefas.create({
      titulo: t.titulo,
      clienteId: t.cliente.id,
      tipo: t.tipo,
      status: t.status,
      prioridade: t.prioridade,
    });
  }

  await store.Notificacoes.create({ tipo: 'sla', titulo: 'SLA em atraso', descricao: 'O atendimento de Lucas Pereira está em atraso.', clienteId: lucas.id, atendimentoId: convs[3].id });
  await store.Notificacoes.create({ tipo: 'lead', titulo: 'Novo lead cadastrado', descricao: 'Camila Rocha foi cadastrada como lead.', clienteId: camila.id });
  await store.Notificacoes.create({ tipo: 'atendimento', titulo: 'Novo atendimento', descricao: 'Atendimento aberto para Maria da Silva.', clienteId: maria.id, atendimentoId: convs[0].id });

  return { clientes: clientes.length, atendimentos: convs.length, tarefas: tarefas.length, notificacoes: 3 };
}

module.exports = { seed };
