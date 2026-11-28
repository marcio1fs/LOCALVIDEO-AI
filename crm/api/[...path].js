'use strict';

/**
 * Função serverless da Vercel — roteamento total do CRM.
 * Usa o handler compartilhado (lib/handler.js), que também roda no
 * servidor local, mantendo o mesmo comportamento.
 *
 * Na Vercel:
 *   /api/*   -> esta função (API REST + webhooks sob /api/webhook/*)
 *   /        -> frontend estático (rewrite em vercel.json -> frontend/)
 */

const { handleRequest } = require('../lib/handler');

module.exports = async function handler(req, res) {
  return handleRequest(req, res);
};
