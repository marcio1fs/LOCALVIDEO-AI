#!/usr/bin/env node
'use strict';

/**
 * Importa os fluxos do CRM para uma instância n8n (Cloud ou self-hosted)
 * via API REST do n8n.
 *
 * Uso:
 *   N8N_API_KEY=sua-chave-api N8N_BASE_URL=https://mastercrm.app.n8n.cloud node scripts/import-n8n.mjs
 *
 *   # opcional: não importa, só valida a chave e lista fluxos existentes
 *   N8N_API_KEY=... N8N_BASE_URL=... node scripts/import-n8n.mjs --dry-run
 *
 * Onde obter a API key: n8n -> Settings -> API -> "Create API key".
 */

import { readFileSync, readdirSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const WORKFLOWS_DIR = join(__dirname, '..', 'n8n', 'workflows');

const N8N_BASE_URL = (process.env.N8N_BASE_URL || 'https://mastercrm.app.n8n.cloud').replace(/\/$/, '');
const N8N_API_KEY = process.env.N8N_API_KEY || '';
const DRY_RUN = process.argv.includes('--dry-run');

if (!N8N_API_KEY) {
  console.error('\n✗ Defina a variável N8N_API_KEY.\n');
  console.error('  Exemplo:');
  console.error('  N8N_API_KEY=sua-chave N8N_BASE_URL=https://mastercrm.app.n8n.cloud node scripts/import-n8n.mjs\n');
  process.exit(1);
}

const headers = {
  'X-N8N-API-KEY': N8N_API_KEY,
  'Content-Type': 'application/json',
};

async function api(method, path, body) {
  const res = await fetch(`${N8N_BASE_URL}/api/v1${path}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  let json;
  try { json = JSON.parse(text); } catch { json = text; }
  if (!res.ok) {
    throw new Error(`HTTP ${res.status} — ${typeof json === 'string' ? json : JSON.stringify(json)}`);
  }
  return json;
}

async function main() {
  console.log(`\nInstância n8n: ${N8N_BASE_URL}`);
  console.log(`Modo: ${DRY_RUN ? 'VALIDAÇÃO (dry-run)' : 'IMPORTAR'}\n`);

  // 1. Valida a chave API listando os fluxos existentes
  console.log('Validando chave API…');
  try {
    const existing = await api('GET', '/workflows');
    const list = Array.isArray(existing) ? existing : existing.data || [];
    console.log(`✓ Chave válida. ${list.length} fluxo(s) existente(s).\n`);
  } catch (err) {
    console.error(`✗ Falha na validação: ${err.message}`);
    console.error('  Verifique a N8N_API_KEY e a N8N_BASE_URL.\n');
    process.exit(1);
  }

  if (DRY_RUN) {
    console.log('Dry-run concluído. Nenhum fluxo foi importado.\n');
    return;
  }

  // 2. Importa cada workflow
  const files = readdirSync(WORKFLOWS_DIR).filter((f) => f.endsWith('.json'));
  console.log(`Importando ${files.length} fluxos…\n`);

  let ok = 0;
  let fail = 0;
  for (const file of files) {
    const raw = readFileSync(join(WORKFLOWS_DIR, file), 'utf8');
    const workflow = JSON.parse(raw);
    // o create da API não aceita id/versionId de um fluxo já existente
    const payload = {
      name: workflow.name,
      nodes: workflow.nodes,
      connections: workflow.connections,
      settings: workflow.settings || { executionOrder: 'v1' },
      pinData: workflow.pinData || {},
      tags: workflow.tags || [],
      meta: workflow.meta || { templateCredsSetupCompleted: true },
      active: false,
    };
    try {
      const created = await api('POST', '/workflows', payload);
      const id = created.id || (created.data && created.data.id) || '?';
      console.log(`  ✓ ${file} -> "${workflow.name}" (id ${id})`);
      ok++;
    } catch (err) {
      console.error(`  ✗ ${file} -> ${err.message}`);
      fail++;
    }
  }

  console.log(`\nResumo: ${ok} importado(s), ${fail} com falha(s).`);
  if (ok > 0) {
    console.log('\nDepois: acesse a instância n8n, abra cada fluxo, ative-o e configure:');
    console.log('  - credenciais dos nós HTTP Request (Slack/e-mail);');
    console.log('  - a URL pública da API do CRM nos nós que fazem callback;');
    console.log('  - os caminhos dos webhooks, se necessário.\n');
  }
  process.exit(fail > 0 ? 1 : 0);
}

main().catch((err) => {
  console.error('Erro inesperado:', err.message);
  process.exit(1);
});
