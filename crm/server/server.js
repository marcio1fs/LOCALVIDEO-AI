'use strict';

/**
 * Servidor local do CRM de atendimento.
 * Usa o handler compartilhado (lib/handler.js), que também é usado pela
 * função serverless da Vercel — assim o comportamento é idêntico em ambos.
 *
 * Rodar:  node server/server.js   (ou: npm run dev)
 */

const http = require('http');
const fs = require('fs');
const path = require('path');

const { handleRequest } = require('../lib/handler');
const notify = require('../lib/notify');
const { seed } = require('../lib/seed');

const PORT = Number(process.env.CRM_PORT || 4000);
const HOST = process.env.CRM_HOST || '0.0.0.0';

const server = http.createServer((req, res) => {
  handleRequest(req, res).catch((err) => {
    console.error(err);
    if (!res.headersSent) {
      res.writeHead(500, { 'Content-Type': 'application/json; charset=utf-8' });
      res.end(JSON.stringify({ error: 'Erro interno', detalhe: err.message }));
    }
  });
});

// Inicializa o notificador (SMTP) e seed automático na primeira inicializacao.
notify.init();
const dataFile = process.env.CRM_DATA_FILE || path.join(__dirname, 'data.json');
if (!fs.existsSync(dataFile)) {
  seed().then((r) => console.log('[seed] dados iniciais criados:', r));
}

server.listen(PORT, HOST, () => {
  console.log(`\n  CRM de Atendimento rodando em http://${HOST}:${PORT}\n`);
  console.log('  Frontend:  http://localhost:' + PORT);
  console.log('  API:       http://localhost:' + PORT + '/api');
  console.log('  Webhooks:  http://localhost:' + PORT + '/webhook/*\n');
});
