"""Página inicial (painel de status) do Control Plane.

Serve HTML estático na raiz `/` para que o preview do ambiente e qualquer
visitante humano vejam imediatamente o estado do serviço — em vez do 404 que
existia quando apenas os endpoints de API estavam publicados.

- A página é PÚBLICA e mostra somente dados não sensíveis (/api/v1/health e
  /api/v1/meta/config — sem segredos, já garantido por teste).
- O painel de GPU/storage usa a MESMA autenticação da API (X-API-Key digitada
  pelo operador; fica apenas em memória no navegador, nunca enviada a terceiros).
- Chamadas usam URLs RELATIVAS (funciona sob proxy do preview e em produção).
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["Painel"])

LANDING_HTML = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>LocalVideo AI — Control Plane</title>
<style>
  :root{--bg:#0b1020;--card:#131a2e;--line:#232c4a;--txt:#e8ecf8;--mut:#93a0c2;
        --ok:#39d98a;--warn:#f5b942;--err:#f26d6d;--acc:#6c8cff}
  *{box-sizing:border-box;margin:0;padding:0}
  body{font:15px/1.55 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
       background:var(--bg);color:var(--txt);min-height:100vh;padding:32px 16px}
  .wrap{max-width:960px;margin:0 auto}
  h1{font-size:22px;margin-bottom:4px}
  .sub{color:var(--mut);margin-bottom:24px}
  .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px}
  .card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px}
  .card h2{font-size:13px;text-transform:uppercase;letter-spacing:.08em;color:var(--mut);margin-bottom:12px}
  .row{display:flex;justify-content:space-between;gap:12px;padding:4px 0;font-size:14px}
  .row .k{color:var(--mut)}
  .pill{padding:2px 10px;border-radius:99px;font-size:12px;font-weight:600}
  .ok{background:#123a29;color:var(--ok)} .err{background:#3a1212;color:var(--err)}
  .warn{background:#3a2e12;color:var(--warn)} .neut{background:#1c2340;color:var(--mut)}
  .big{font-size:26px;font-weight:700;margin:6px 0}
  input{width:100%;padding:9px 11px;border-radius:8px;border:1px solid var(--line);
        background:#0e142a;color:var(--txt);font-size:14px;margin:6px 0}
  button{padding:8px 14px;border-radius:8px;border:1px solid var(--acc);background:var(--acc);
         color:#fff;font-weight:600;font-size:13px;cursor:pointer}
  button:hover{filter:brightness(1.1)}
  .msg{font-size:13px;color:var(--mut);margin-top:8px;word-break:break-word}
  .msg.err{color:var(--err)} .msg.ok{color:var(--ok)}
  a{color:var(--acc);text-decoration:none}
  footer{margin-top:26px;color:var(--mut);font-size:12.5px;line-height:1.7}
  code{background:#0e142a;padding:1px 6px;border-radius:6px;font-size:12.5px}
</style>
</head>
<body>
<div class="wrap">
  <h1>LocalVideo AI — Control Plane</h1>
  <p class="sub">GPU sob demanda (Vast.ai) · Fase 1 — fundação e adaptador do provedor</p>

  <div class="grid">
    <div class="card">
      <h2>Serviço</h2>
      <div class="row"><span class="k">Estado</span><span id="health" class="pill neut">verificando…</span></div>
      <div class="row"><span class="k">Ambiente</span><span id="env">—</span></div>
      <div class="row"><span class="k">Chave Vast.ai</span><span id="vastkey">—</span></div>
      <div class="row"><span class="k">Mutações (cobrança)</span><span id="mut">—</span></div>
      <div class="row"><span class="k">Orçamento mensal</span><span id="budget">—</span></div>
      <div class="row"><span class="k">Rate limit</span><span id="rl">—</span></div>
    </div>

    <div class="card">
      <h2>Painel GPU Cloud (requer chave de API)</h2>
      <input id="apikey" type="password" placeholder="Cole a chave (LV_LOCALVIDEO_API_KEY ou admin)">
      <button onclick="refresh()">Conectar</button>
      <div id="gpustate" class="big">—</div>
      <div id="gpumsg" class="msg">Estado do GPU Manager aparecerá aqui.</div>
      <div id="gpusession" class="msg"></div>
      <div id="gpubudget" class="msg"></div>
    </div>

    <div class="card">
      <h2>Armazenamento persistente</h2>
      <div id="storage" class="msg">Use a chave acima e clique em Conectar para consultar /api/v1/storage/status.</div>
    </div>

    <div class="card">
      <h2>Ofertas compatíveis (Vast.ai)</h2>
      <button onclick="estimate()">Estimar custo da sessão</button>
      <div id="estimate" class="msg">Consulta ofertas reais e calcula preço estimado (sem criar nada).</div>
    </div>
  </div>

  <footer>
    Documentação interativa da API: <a href="/docs">/docs</a> · OpenAPI: <a href="/openapi.json">/openapi.json</a><br>
    Endpoints principais: <code>GET /api/v1/gpu/status</code> · <code>POST /api/v1/gpu/start</code> ·
    <code>POST /api/v1/gpu/stop</code> · <code>POST /api/v1/gpu/offers</code> ·
    <code>GET /api/v1/gpu/cost-estimate</code> · <code>GET /api/v1/gpu/usage</code> ·
    <code>GET /api/v1/storage/status</code><br>
    Autenticação: header <code>X-API-Key</code>. Sem <code>LV_VAST_API_KEY</code> configurada no
    servidor, rotas de ofertas respondem 503 — comportamento esperado da Fase 1.
    A interface completa do aplicativo desktop (Tauri) chega na Fase 5.
  </footer>
</div>

<script>
const $ = id => document.getElementById(id);
let key = "";

function pill(el, ok, text){ el.textContent = text; el.className = "pill " + (ok ? "ok" : "err"); }

async function get(url, withKey=false){
  const headers = withKey && key ? {"X-API-Key": key} : {};
  const r = await fetch(url, {headers});
  let body = null;
  try { body = await r.json(); } catch(e){}
  return {ok: r.ok, status: r.status, body};
}

async function loadMeta(){
  const h = await get("/api/v1/health");
  pill($("health"), h.ok, h.ok ? "ONLINE" : "INDISPONÍVEL");
  const c = await get("/api/v1/meta/config");
  if (c.ok){
    $("env").textContent = c.body.environment;
    $("vastkey").innerHTML = c.body.vast_api_key_configured
      ? '<span class="pill ok">configurada</span>' : '<span class="pill err">não configurada</span>';
    $("mut").innerHTML = c.body.vast_mutations_enabled
      ? '<span class="pill warn">HABILITADAS (gera cobrança)</span>' : '<span class="pill neut">desabilitadas</span>';
    $("budget").textContent = "R$ " + c.body.gpu_monthly_budget_brl.toFixed(2);
    $("rl").textContent = c.body.rate_limit_requests_per_minute + " req/min";
  }
}

async function refresh(){
  key = $("apikey").value.trim();
  if (!key){ $("gpumsg").textContent = "Digite a chave de API do Control Plane."; return; }
  $("gpumsg").textContent = "consultando…"; $("gpumsg").className = "msg";
  const s = await get("/api/v1/gpu/status", true);
  if (!s.ok){
    const m = s.body && s.body.error ? s.body.error.message : ("HTTP " + s.status);
    $("gpustate").textContent = "—";
    $("gpumsg").textContent = "Falha: " + m; $("gpumsg").className = "msg err";
    return;
  }
  const st = s.body;
  $("gpustate").textContent = st.state;
  $("gpumsg").textContent = st.message;
  $("gpusession").textContent = st.instance_id
    ? ("Instância " + st.instance_id + " · sessão " + st.session.elapsed_hours + " h · acúmulo R$ " + st.session.accrual_brl.toFixed(2))
    : "Nenhuma instância ativa.";
  $("gpubudget").textContent = "Orçamento: R$ " + st.budget.committed_brl.toFixed(2) + " de R$ " +
    st.budget.budget_brl.toFixed(2) + " comprometidos (" + Math.round(st.budget.utilization*100) + "%) · " + st.budget.state;
  st.budget.warnings.forEach(w => {
    $("gpubudget").textContent += " — " + w;
  });
  const stg = await get("/api/v1/storage/status", true);
  if (stg.ok){
    const vols = stg.body.volumes;
    $("storage").textContent = vols.length
      ? vols.map(v => "Volume " + v.volume_id + " · host " + v.machine_id + " · " + v.capacity_gb + " GB · " + v.state + " · montado em " + v.mount_path).join(" | ")
      : "Nenhum volume registrado. Contrate na Fase 2 (com confirmação de custo).";
  } else {
    $("storage").textContent = "Falha ao consultar armazenamento (HTTP " + stg.status + ").";
  }
}

async function estimate(){
  const el = $("estimate");
  if (!key){ el.textContent = "Conecte-se com a chave primeiro."; return; }
  el.textContent = "consultando ofertas…";
  const r = await fetch("/api/v1/gpu/cost-estimate", {headers: {"X-API-Key": key}});
  let body = null; try { body = await r.json(); } catch(e){}
  if (!r.ok){
    el.textContent = "Falha: " + (body && body.error ? body.error.message : "HTTP " + r.status);
    return;
  }
  if (!body.feasible){
    el.textContent = body.message || "Nenhuma oferta compatível no momento.";
    return;
  }
  const o = body.offer, c = body.cost_estimate;
  el.textContent = o.gpu_name + " (" + Math.round(o.vram_mb/1024) + " GB) · US$ " +
    c.gpu_hourly_usd.toFixed(2) + "/h · sessão estimada: US$ " + c.total_usd.toFixed(2) +
    " ≈ R$ " + c.total_brl.toFixed(2) + " (" + c.hours + " h). Estimativa — não cria instância.";
}

loadMeta();
</script>
</body>
</html>
"""


@router.get("/", response_class=HTMLResponse, include_in_schema=True)
async def landing() -> HTMLResponse:
    """Página de status pública (sem segredos)."""
    return HTMLResponse(content=LANDING_HTML, status_code=200)
