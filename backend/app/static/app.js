"use strict";

/* LocalVideo AI — painel web (antecipação da Fase 5).
   Vanilla JS, sem build. Comunica-se com o Control Plane via URLs relativas
   e header X-API-Key. A chave fica só em memória do navegador. */

const $ = (id) => document.getElementById(id);
const fmtBRL = (v) => new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }).format(v || 0);
const fmtUSD = (v) => (v == null ? "—" : "US$ " + Number(v).toFixed(2));
const fmtTime = (ts) => (ts ? new Date(ts * 1000).toLocaleTimeString("pt-BR") : "—");
const fmtHours = (h) => (h == null ? "—" : Number(h).toLocaleString("pt-BR", { maximumFractionDigits: 2 }) + " h");

const STATE_BADGES = {
  OFFLINE: ["neut", "OFFLINE"],
  STARTING: ["warn", "INICIANDO"],
  PROVISIONING: ["warn", "PROVISIONANDO"],
  CHECKING: ["warn", "VALIDANDO"],
  READY: ["ok", "PRONTA"],
  BUSY: ["ok", "OCUPADA"],
  IDLE: ["warn", "OCIOSA"],
  STOPPING: ["warn", "ENCERRANDO"],
  ERROR: ["err", "ERRO"],
  RECOVERING: ["warn", "RECUPERANDO"],
  HOST_UNAVAILABLE: ["err", "HOST INDISPONÍVEL"],
  VOLUME_UNAVAILABLE: ["err", "VOLUME INDISPONÍVEL"],
  BUDGET_LIMIT_REACHED: ["err", "ORÇAMENTO ESGOTADO"],
};
const TRANSITIONAL = new Set(["STARTING", "PROVISIONING", "CHECKING", "STOPPING", "RECOVERING"]);
const SESSION_ACTIVE = new Set(["READY", "BUSY", "IDLE"]);

let key = "";
let connected = false;
let pollTimer = null;
let lastStatus = null;

/* ------------------------------------------------------------------ */
/* Infra de chamadas                                                   */
/* ------------------------------------------------------------------ */

async function api(path, { method = "GET", body = null, needKey = true } = {}) {
  let r;
  try {
    r = await fetch(path, {
      method,
      headers: {
        "Content-Type": "application/json",
        ...(needKey && key ? { "X-API-Key": key } : {}),
      },
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch (e) {
    return { ok: false, status: 0, body: { error: { code: "network", message: "Falha de rede: " + e.message } } };
  }
  let payload = null;
  try { payload = await r.json(); } catch (e) { /* sem corpo */ }
  if (!r.ok && !payload) payload = { error: { code: "http_" + r.status, message: "HTTP " + r.status } };
  return { ok: r.ok, status: r.status, body: payload };
}

function errMsg(body) {
  return body && body.error && body.error.message ? body.error.message : JSON.stringify(body);
}

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function setPill(el, cls, text) { el.className = "pill " + cls; el.textContent = text; }

/* ------------------------------------------------------------------ */
/* Modal (promise-based)                                               */
/* ------------------------------------------------------------------ */

function openModal({ title, bodyHTML, okText = "Confirmar", okClass = "primary", validate = null }) {
  return new Promise((resolve) => {
    $("modalTitle").textContent = title;
    $("modalBody").innerHTML = bodyHTML;
    $("modalMsg").textContent = ""; $("modalMsg").className = "msg";
    const ok = $("modalOk"), cancel = $("modalCancel");
    ok.textContent = okText; ok.className = okClass;
    $("modal").classList.remove("hidden");
    const close = (result) => {
      $("modal").classList.add("hidden");
      ok.onclick = cancel.onclick = null;
      resolve(result);
    };
    ok.onclick = () => {
      if (validate) {
        const problem = validate();
        if (problem) { $("modalMsg").textContent = problem; $("modalMsg").className = "msg err"; return; }
      }
      close(true);
    };
    cancel.onclick = () => close(false);
  });
}

function modalError(title, message) {
  return openModal({ title, bodyHTML: `<div class="modal-body"><p class="msg err">${escapeHtml(message)}</p></div>`, okText: "Fechar" })
    .then(() => false);
}

/* ------------------------------------------------------------------ */
/* Conexão e polling                                                   */
/* ------------------------------------------------------------------ */

async function connect() {
  if (connected) { disconnect(); return; }
  key = $("apikey").value.trim();
  if (!key) { flashConn("Digite a chave de API (client ou admin).", true); return; }
  const s = await api("/api/v1/gpu/status");
  if (!s.ok) { flashConn("Falha ao conectar: " + errMsg(s.body), true); return; }
  connected = true;
  setPill($("connState"), "ok", "conectado");
  $("btnConnect").textContent = "Desconectar";
  $("apikey").disabled = true;
  ["btnStart", "btnStop", "btnEstimate", "btnOffers", "btnSaveBudget"].forEach((id) => ($(id).disabled = false));
  await loadProfile();
  await pollOnce();
  schedulePoll();
}

function disconnect() {
  connected = false; key = ""; lastStatus = null;
  clearTimeout(pollTimer); pollTimer = null;
  setPill($("connState"), "neut", "desconectado");
  $("btnConnect").textContent = "Conectar";
  $("apikey").disabled = false;
  ["btnStart", "btnStop", "btnEstimate", "btnOffers", "btnSaveBudget"].forEach((id) => ($(id).disabled = true));
  $("gpustate").textContent = "—"; $("gpustate").className = "pill neut";
  $("gpumsg").textContent = "Conecte-se para ver o estado.";
  $("alerts").innerHTML = "";
  $("historyList").innerHTML = ""; $("ledgerList").innerHTML = "";
  $("storageBody").textContent = "—"; $("offersBody").textContent = "Clique em “Ver ofertas”.";
}

function flashConn(text, isErr) {
  const el = $("gpumsg");
  el.textContent = text; el.className = isErr ? "msg err" : "muted";
}

function schedulePoll() {
  clearTimeout(pollTimer);
  const interval = lastStatus && TRANSITIONAL.has(lastStatus.state) ? 2000 : 5000;
  pollTimer = setTimeout(async () => {
    if (!connected) return;
    if (!document.hidden) await pollOnce();
    schedulePoll();
  }, interval);
}

async function pollOnce() {
  const [s, stg, u] = await Promise.all([
    api("/api/v1/gpu/status"),
    api("/api/v1/storage/status"),
    api("/api/v1/gpu/usage"),
  ]);
  if (!s.ok) {
    if (s.status === 401 || s.status === 403) { disconnect(); flashConn("Chave inválida ou sem permissão. Conecte-se novamente.", true); }
    return;
  }
  lastStatus = s.body;
  renderStatus(s.body);
  if (stg.ok) renderStorage(stg.body);
  if (u.ok) renderUsage(u.body);
}

/* ------------------------------------------------------------------ */
/* Renderização                                                        */
/* ------------------------------------------------------------------ */

function renderStatus(st) {
  const [cls, label] = STATE_BADGES[st.state] || ["neut", st.state];
  setPill($("gpustate"), cls, label);
  $("gpuSpinner").classList.toggle("hidden", !TRANSITIONAL.has(st.state));
  $("gpumsg").textContent = st.message; $("gpumsg").className = "muted";

  $("provider").textContent = st.provider + (st.mutations_enabled ? " (cobrança habilitada)" : " (cobrança desabilitada)");
  $("instance").textContent = st.instance_id ?? "—";
  const gpu = st.gpu;
  $("gpumodel").textContent = gpu ? `${gpu.gpu_name} · ${Math.round(gpu.vram_mb / 1024)} GB VRAM` : "—";
  $("elapsed").textContent = st.instance_id ? fmtHours(st.session.elapsed_hours) : "—";
  $("accrual").textContent = st.instance_id ? fmtBRL(st.session.accrual_brl) + " (estimado)" : "—";
  $("queue").textContent = `${st.queue_size} / ${st.max_concurrent_jobs} · Job Manager na Fase 3`;
  $("idle").textContent = `${st.idle_timeout_minutes} min · automático na Fase 4`;

  $("btnStart").disabled = !connected || SESSION_ACTIVE.has(st.state) || TRANSITIONAL.has(st.state);
  $("btnStop").disabled = !connected || st.state === "OFFLINE";

  renderBudget(st.budget);
  renderAlerts(st);
}

function renderBudget(b) {
  if (!b) return;
  $("bLimit").textContent = fmtBRL(b.budget_brl);
  $("bCommitted").textContent = fmtBRL(b.committed_brl) + ` (${Math.round(b.utilization * 100)}%)`;
  $("bExternal").textContent = fmtBRL(b.external_brl);
  $("bRemaining").textContent = fmtBRL(b.remaining_brl);
  const map = { OK: "ok", ALERT_70: "warn", BLOCK_90: "err", LIMIT_REACHED: "err" };
  setPill($("bState"), map[b.state] || "neut", b.state);

  const fill = $("budgetFill");
  fill.style.width = Math.min(b.utilization * 100, 100) + "%";
  fill.className = "budget-fill " + (b.state === "OK" ? "" : b.state === "ALERT_70" ? "warn" : "err");
  if ($("budgetInput").value === "" ) $("budgetInput").placeholder = String(b.budget_brl);
}

function renderAlerts(st) {
  const items = [];
  if (!st.provider_configured) items.push(["err", "Chave da Vast.ai não configurada no servidor (LV_VAST_API_KEY). Ofertas e sessões ficarão indisponíveis."]);
  if (!st.mutations_enabled) items.push(["warn", "Operações que geram cobrança estão DESABILITADAS (LV_VAST_ENABLE_MUTATIONS=false): “Iniciar sessão” não criará instâncias."]);
  switch (st.state) {
    case "STARTING": case "PROVISIONING": case "CHECKING":
      items.push(["info", "GPU inicializando — a sessão só ficará PRONTA após a validação real do worker."]); break;
    case "READY": items.push(["ok", "GPU pronta para geração."]); break;
    case "ERROR": items.push(["err", "Falha na sessão de GPU: " + st.message]); break;
    case "HOST_UNAVAILABLE": items.push(["err", "Host indisponível: nenhuma oferta compatível agora. Tente novamente mais tarde."]); break;
    case "VOLUME_UNAVAILABLE": items.push(["err", "Volume indisponível: não há oferta no host físico do volume registrado. Os dados permanecem preservados."]); break;
    case "BUDGET_LIMIT_REACHED": items.push(["err", "Início bloqueado pelo controle financeiro. Ajuste o orçamento ou aguarde o ciclo mensal."]); break;
    case "STOPPING": items.push(["info", "Encerrando sessão de GPU com procedimento seguro…"]); break;
  }
  const b = st.budget || {};
  if (b.state === "ALERT_70") items.push(["warn", `Orçamento próximo do limite (${Math.round(b.utilization * 100)}%).`]);
  (b.warnings || []).forEach((w) => items.push(["warn", w]));

  $("alerts").innerHTML = items
    .map(([lvl, text]) => `<div class="alert ${lvl}">${escapeHtml(text)}</div>`)
    .join("");
}

function renderStorage(stg) {
  const vols = stg.volumes || [];
  if (!vols.length) {
    $("storageBody").innerHTML = "<p class='muted'>Nenhum volume registrado. Volumes são contratados na Fase 2, com confirmação de custo.</p>";
    return;
  }
  $("storageBody").innerHTML = vols.map((v) => {
    const pct = v.capacity_gb ? Math.round((v.used_gb / v.capacity_gb) * 100) : 0;
    const stateCls = v.state === "AVAILABLE" ? "ok" : v.state === "IN_USE" ? "info" : "err";
    return `
      <div class="vol">
        <div class="row"><strong>Volume ${v.volume_id}</strong><span class="pill ${stateCls}">${v.state}</span></div>
        <div class="vol-bar"><div class="vol-fill" style="width:${pct}%"></div></div>
        <div class="row"><span class="muted">Usado</span><span>${v.used_gb} / ${v.capacity_gb} GB (${pct}%) · livre ${v.free_gb} GB</span></div>
        <div class="row"><span class="muted">Host físico</span><span>${v.machine_id ?? "—"}</span></div>
        <div class="row"><span class="muted">Montagem</span><span>${escapeHtml(v.mount_path)}</span></div>
        ${v.note ? `<div class="msg">${escapeHtml(v.note)}</div>` : ""}
      </div>`;
  }).join("") + `<p class="msg">${escapeHtml(stg.note)}</p>`;
}

function renderUsage(u) {
  const hist = (u.history || []).slice(0, 40);
  $("historyList").innerHTML = hist.length
    ? hist.map((h) => {
        const [cls] = STATE_BADGES[h.state] || ["neut", h.state];
        return `<li><span class="t">${fmtTime(h.ts)}</span><span class="pill ${cls}">${h.state}</span><span>${escapeHtml(h.message)}</span></li>`;
      }).join("")
    : "<li class='muted'>sem eventos ainda</li>";

  const ledger = (u.ledger || []).slice(-40).reverse();
  $("ledgerList").innerHTML = ledger.length
    ? ledger.map((e) =>
        `<li><span class="t">${fmtTime(e.ts)}</span><strong>${e.kind}</strong><span>${fmtBRL(e.brl)}</span><span class="muted">${escapeHtml(e.note)}</span></li>`
      ).join("")
    : "<li class='muted'>sem lançamentos ainda</li>";
}

/* ------------------------------------------------------------------ */
/* Perfil de hardware (§4)                                             */
/* ------------------------------------------------------------------ */

async function loadProfile() {
  const r = await api("/api/v1/gpu/hardware-profile");
  if (!r.ok) return;
  const p = r.body;
  $("pGpus").value = (p.allowed_gpus || []).join(", ");
  $("pVram").value = Math.round((p.min_vram_mb || 0) / 1024);
  $("pRam").value = Math.round((p.min_cpu_ram_mb || 0) / 1024);
  $("pDisk").value = p.min_disk_gb ?? "";
  $("pRel").value = p.min_reliability ?? "";
  $("pMaxDph").value = p.max_dph_total ?? "";
}

function readProfile() {
  const req = {};
  const gpus = $("pGpus").value.split(",").map((s) => s.trim()).filter(Boolean);
  if (gpus.length) req.allowed_gpus = gpus;
  if ($("pVram").value) req.min_vram_mb = Math.round(parseFloat($("pVram").value) * 1024);
  if ($("pRam").value) req.min_cpu_ram_mb = Math.round(parseFloat($("pRam").value) * 1024);
  if ($("pDisk").value) req.min_disk_gb = parseFloat($("pDisk").value);
  if ($("pRel").value) req.min_reliability = parseFloat($("pRel").value);
  if ($("pMaxDph").value) req.max_dph_total = parseFloat($("pMaxDph").value);
  return req;
}

function estimatedHours() {
  const v = parseFloat($("pHours").value);
  return Number.isFinite(v) && v > 0 ? v : undefined;
}

/* ------------------------------------------------------------------ */
/* Ações: iniciar / encerrar / estimar / ofertas / orçamento           */
/* ------------------------------------------------------------------ */

async function startFlow() {
  const est = await api("/api/v1/gpu/cost-estimate?estimated_hours=" + (estimatedHours() ?? ""), { needKey: true });
  if (!est.ok) return modalError("Não foi possível estimar o custo", errMsg(est.body));
  if (!est.body.feasible) {
    return modalError("Sem oferta compatível", est.body.message || "Nenhuma oferta atende ao perfil de hardware agora.");
  }
  const o = est.body.offer, c = est.body.cost_estimate;
  const ok = await openModal({
    title: "Confirmar início de sessão (gera cobrança)",
    bodyHTML: `
      <div class="modal-body">
        <div class="line"><span>GPU</span><span>${escapeHtml(o.gpu_name)} · ${Math.round(o.vram_mb / 1024)} GB</span></div>
        <div class="line"><span>Preço</span><span>${fmtUSD(c.gpu_hourly_usd)}/h</span></div>
        <div class="line"><span>Horas estimadas</span><span>${c.hours}</span></div>
        <div class="line"><span>Total estimado</span><strong>${fmtUSD(c.total_usd)} ≈ ${fmtBRL(c.total_brl)}</strong></div>
        <p class="msg">Estimativa baseada no preço publicado da oferta. A cobrança efetiva é da Vast.ai
        e o encerramento automático (Fase 4) limitará o tempo ocioso.</p>
      </div>`,
    okText: "Iniciar sessão",
    okClass: "danger",
  });
  if (!ok) return;
  const r = await api("/api/v1/gpu/start", {
    method: "POST",
    body: { requirements: readProfile(), estimated_hours: estimatedHours(), confirm_cost: true },
  });
  await handleActionResult(r, "Início de sessão");
  pollOnce();
}

async function stopFlow() {
  const ok = await openModal({
    title: "Encerrar sessão de GPU",
    bodyHTML: `
      <div class="modal-body">
        <label class="check"><input type="radio" name="stopmode" value="stop" checked>
          Parar instância — interrompe a cobrança de GPU; disco/instância permanecem.</label>
        <label class="check"><input type="radio" name="stopmode" value="destroy">
          Destruir instância — IRREVERSÍVEL; encerra todos os custos da instância.</label>
        <label class="check" id="persistRow"><input type="checkbox" id="persistCheck">
          Confirmo que os dados importantes estão no volume persistente e o volume está protegido.</label>
        <p class="msg">O volume NUNCA é apagado automaticamente. "Parar" não exige confirmação.</p>
      </div>`,
    okText: "Encerrar",
    validate: () => {
      const mode = document.querySelector('input[name="stopmode"]:checked').value;
      if (mode === "destroy" && !$("persistCheck").checked) {
        return "Destruir exige a confirmação de persistência dos dados.";
      }
      return null;
    },
  });
  if (!ok) return;
  const mode = document.querySelector('input[name="stopmode"]:checked').value;
  const r = await api("/api/v1/gpu/stop", {
    method: "POST",
    body: { mode, data_persisted_confirmed: mode === "destroy" },
  });
  await handleActionResult(r, "Encerramento");
  pollOnce();
}

async function estimateFlow() {
  const r = await api("/api/v1/gpu/cost-estimate?estimated_hours=" + (estimatedHours() ?? ""), { needKey: true });
  if (!r.ok) { $("offersBody").innerHTML = `<p class="msg err">${escapeHtml(errMsg(r.body))}</p>`; return; }
  const p = r.body;
  if (!p.feasible) {
    $("offersBody").innerHTML = `<p class="msg err">${escapeHtml(p.message || "Sem oferta compatível.")}</p>
      <div class="chips">${Object.entries(p.rejection_summary || {}).map(([k, v]) => `<span class="chip">${escapeHtml(k)}: ${v}</span>`).join("")}</div>`;
    return;
  }
  const c = p.cost_estimate;
  $("offersBody").innerHTML = `
    <p>Melhor oferta: <strong>${escapeHtml(p.offer.gpu_name)}</strong> · ${Math.round(p.offer.vram_mb / 1024)} GB ·
    ${fmtUSD(c.gpu_hourly_usd)}/h · sessão (${c.hours} h): <strong>${fmtUSD(c.total_usd)} ≈ ${fmtBRL(c.total_brl)}</strong></p>
    <p class="msg">${p.considered} ofertas consideradas · ${escapeHtml(p.offer.geolocation || "")} ·
    confiabilidade ${p.offer.reliability}</p>`;
}

async function offersFlow() {
  $("offersBody").innerHTML = "<p class='muted'>consultando marketplace…</p>";
  const r = await api("/api/v1/gpu/offers", {
    method: "POST",
    body: { requirements: readProfile(), estimated_hours: estimatedHours() },
  });
  if (!r.ok) { $("offersBody").innerHTML = `<p class="msg err">${escapeHtml(errMsg(r.body))}</p>`; return; }
  const p = r.body;
  if (!p.feasible) {
    $("offersBody").innerHTML = `<p class="msg err">${escapeHtml(p.message || "Sem oferta compatível.")}</p>
      <div class="chips">${Object.entries(p.rejection_summary || {}).map(([k, v]) => `<span class="chip">${escapeHtml(k)}: ${v}</span>`).join("")}</div>`;
    return;
  }
  const rows = (p.top_offers || []).map((o, i) => `
    <tr class="${i === 0 ? "best" : ""}">
      <td>${escapeHtml(o.gpu_name || "—")}</td>
      <td>${o.vram_mb ? Math.round(o.vram_mb / 1024) + " GB" : "—"}</td>
      <td>${fmtUSD(o.dph_total_usd)}</td>
      <td>${o.reliability ?? "—"}</td>
      <td>${o.disk_gb ?? "—"}</td>
      <td>${escapeHtml(o.geolocation || "—")}</td>
    </tr>`).join("");
  const chips = Object.entries(p.rejection_summary || {}).map(([k, v]) => `<span class="chip">${escapeHtml(k)}: ${v}</span>`).join("");
  $("offersBody").innerHTML = `
    <p><strong>${p.considered}</strong> ofertas consideradas · melhor oferta destacada:</p>
    <table class="offers">
      <thead><tr><th>GPU</th><th>VRAM</th><th>US$/h</th><th>Confiab.</th><th>Disco GB</th><th>Região</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
    <div class="chips">${chips}</div>
    <p class="msg">Somente leitura — nada é criado. Volumes locais só funcionam no mesmo host físico do volume registrado (§5).</p>`;
}

async function saveBudget() {
  const body = {};
  if ($("budgetInput").value) body.monthly_budget_brl = parseFloat($("budgetInput").value);
  if ($("rateInput").value) body.usd_to_brl_rate = parseFloat($("rateInput").value);
  const msg = $("budgetMsg");
  if (!Object.keys(body).length) { msg.textContent = "Preencha ao menos um campo."; msg.className = "msg err"; return; }
  const r = await api("/api/v1/gpu/budget", { method: "PATCH", body });
  if (!r.ok) { msg.textContent = "Falha: " + errMsg(r.body); msg.className = "msg err"; return; }
  msg.textContent = "Orçamento salvo e persistido."; msg.className = "msg ok";
  renderBudget(r.body.budget);
  $("budgetInput").value = ""; $("rateInput").value = "";
  pollOnce();
}

async function handleActionResult(r, label) {
  if (r.ok) {
    const st = r.body;
    return modalError(label + " — resultado", `${st.message || "Concluído."}` );
  }
  return modalError(label + " — falha", errMsg(r.body));
}

/* ------------------------------------------------------------------ */
/* Bootstrap                                                           */
/* ------------------------------------------------------------------ */

$("btnConnect").addEventListener("click", connect);
$("apikey").addEventListener("keydown", (e) => { if (e.key === "Enter") connect(); });
$("btnStart").addEventListener("click", startFlow);
$("btnStop").addEventListener("click", stopFlow);
$("btnEstimate").addEventListener("click", estimateFlow);
$("btnOffers").addEventListener("click", offersFlow);
$("btnSaveBudget").addEventListener("click", saveBudget);
$("btnLoadProfile").addEventListener("click", loadProfile);

/* Meta pública (sem chave): estado do serviço nos alertas antes de conectar. */
(async function loadPublicMeta() {
  const h = await api("/api/v1/meta/config", { needKey: false });
  const c = h.body;
  if (h.ok && c) {
    const items = [];
    items.push([c.vast_api_key_configured ? "ok" : "err",
      c.vast_api_key_configured ? "Chave da Vast.ai configurada no servidor."
                                : "Chave da Vast.ai NÃO configurada no servidor (LV_VAST_API_KEY) — ofertas indisponíveis."]);
    items.push([c.vast_mutations_enabled ? "warn" : "info",
      c.vast_mutations_enabled ? "Cobrança HABILITADA: iniciar sessão cria instâncias reais."
                               : "Cobrança desabilitada (LV_VAST_ENABLE_MUTATIONS=false): nenhuma instância é criada."]);
    $("alerts").innerHTML = items.map(([lvl, t]) => `<div class="alert ${lvl}">${escapeHtml(t)}</div>`).join("");
  }
})();
