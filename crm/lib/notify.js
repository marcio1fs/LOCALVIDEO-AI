'use strict';

/**
 * Notify — notificações por e-mail (nodemailer) + registro no app.
 * Funciona no servidor local e no runtime serverless da Vercel.
 */

const store = require('./store');

let transporter = null;
let from = process.env.SMTP_FROM || 'CRM Atendimento <noreply@empresa.com>';

function init() {
  if (process.env.SMTP_HOST) {
    try {
      const nodemailer = require('nodemailer');
      transporter = nodemailer.createTransport({
        host: process.env.SMTP_HOST,
        port: Number(process.env.SMTP_PORT || 587),
        secure: Number(process.env.SMTP_PORT || 587) === 465,
        auth: process.env.SMTP_USER
          ? { user: process.env.SMTP_USER, pass: process.env.SMTP_PASS || '' }
          : undefined,
      });
      console.log('[notify] SMTP configurado — e-mails serão enviados.');
    } catch (err) {
      console.error('[notify] falha ao inicializar nodemailer:', err.message);
    }
  } else {
    console.log('[notify] SMTP não configurado (SMTP_HOST). Notificações por e-mail no modo dev (log no console).');
  }
}

async function sendEmail(to, subject, text) {
  if (!transporter) {
    console.log(`\n[notify:dev] ──────────────────────────────\nPara: ${to}\nAssunto: ${subject}\n\n${text}\n──────────────────────────────\n`);
    return false;
  }
  try {
    await transporter.sendMail({ from, to, subject, text });
    return true;
  } catch (err) {
    console.error('[notify] erro ao enviar e-mail:', err.message);
    return false;
  }
}

/** Registra notificação no app e dispara o e-mail (fire-and-forget seguro). */
async function notificar({ tipo, titulo, descricao, clienteId = null, atendimentoId = null, para = null }) {
  try {
    await store.Notificacoes.create({ tipo, titulo, descricao, clienteId, atendimentoId });
  } catch (e) {
    /* ignora */
  }
  if (para) {
    sendEmail(para, titulo, descricao).catch(() => {});
  }
}

module.exports = { init, notificar, sendEmail, getTransporter: () => transporter };
