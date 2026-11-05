const $ = (selector, root = document) => root.querySelector(selector);
const state = { token: sessionStorage.getItem("stormtrack_token"), account: null, view: "monitor-view", pollTimer: null, satelliteRefreshTimer: null, satelliteFrames: [], satelliteObjectUrl: null, selectedSatelliteFrame: 0 };
const gateNames = [
  ["access_status", "Acesso técnico"],
  ["collection_status", "Coleta automatizada"],
  ["storage_status", "Armazenamento"],
  ["redistribution_status", "Redistribuição"],
];
const gateOptions = ["PENDING", "VERIFIED", "BLOCKED"];

function authHeaders(extra = {}) {
  return state.token ? { ...extra, Authorization: `Bearer ${state.token}` } : extra;
}

async function api(path, options = {}) {
  const headers = authHeaders(options.headers || {});
  if (options.body && !headers["Content-Type"]) headers["Content-Type"] = "application/json";
  const response = await fetch(path, { ...options, headers });
  if (!response.ok) {
    let detail = `Falha (${response.status})`;
    try {
      const body = await response.json();
      if (typeof body.detail === "string") detail = body.detail;
    } catch (_) { /* Keep the HTTP status as the fallback. */ }
    const error = new Error(detail);
    error.status = response.status;
    throw error;
  }
  return response.status === 204 ? null : response.json();
}

function setHealth(status, text) {
  const badge = $("#system-status");
  badge.className = `status-pill ${status}`;
  badge.textContent = text;
}

async function refreshHealth() {
  const apiStatus = $("#api-health");
  const dbStatus = $("#database-health");
  try {
    const health = await api("/api/health");
    apiStatus.textContent = "Disponível";
    apiStatus.style.color = "var(--green)";
    dbStatus.textContent = health.database === "ok" ? "Disponível" : "Verificar";
    dbStatus.style.color = health.database === "ok" ? "var(--green)" : "var(--red)";
    const collector = $("#collector-health");
    if (collector) collector.textContent = health.collection === "enabled" ? "Ativa (opt-in)" : "Desligada";
    if (!state.account) setHealth("status-ok", "API e banco disponíveis");
  } catch (_) {
    apiStatus.textContent = "Indisponível";
    dbStatus.textContent = "Indisponível";
    setHealth("status-error", "API indisponível");
  }
}

function showDashboard(account) {
  document.body.classList.remove("login-mode");
  state.account = account;
  $("#login-view").hidden = true;
  $("#dashboard-view").hidden = false;
  $("#account-label").hidden = false;
  $("#account-label").textContent = `${account.username} · ${account.role === "ADMIN" ? "Administrador" : "Usuário"}`;
  $("#logout-button").hidden = false;
  $("#main-nav").hidden = false;
  $("#create-source-form").hidden = account.role !== "ADMIN";
  for (const element of document.querySelectorAll(".admin-only")) element.hidden = account.role !== "ADMIN";
  setHealth("status-ok", "Sessão autenticada");
  navigate("monitor-view");
  window.StormTrackRegional?.refresh();
  window.StormTrackSurface?.refresh();
  refreshProducts();
  refreshObservations();
  refreshIngestion();
  refreshAnalysisStatus();
  refreshSatelliteFrames();
  if (state.pollTimer) clearInterval(state.pollTimer);
  if (state.satelliteRefreshTimer) clearInterval(state.satelliteRefreshTimer);
  state.pollTimer = setInterval(() => {
    if (state.account && state.view === "monitor-view") {
      refreshObservations();
      refreshIngestion();
      refreshAnalysisStatus();
    }
  }, 60000);
  state.satelliteRefreshTimer = setInterval(() => {
    if (state.account && state.view === "monitor-view") refreshSatelliteFrames();
  }, 30000);
}

function showLogin(message = "") {
  window.StormTrackSurface?.clear();
  window.StormTrackRegional?.clear();
  document.body.classList.add("login-mode");
  window.StormTrackMap.clearObservations();
  window.StormTrackUsers.clear();
  if (state.pollTimer) clearInterval(state.pollTimer);
  if (state.satelliteRefreshTimer) clearInterval(state.satelliteRefreshTimer);
  state.pollTimer = null;
  state.satelliteRefreshTimer = null;
  if (state.satelliteObjectUrl) URL.revokeObjectURL(state.satelliteObjectUrl);
  state.satelliteObjectUrl = null;
  state.account = null;
  state.token = null;
  sessionStorage.removeItem("stormtrack_token");
  $("#dashboard-view").hidden = true;
  $("#main-nav").hidden = true;
  $("#login-view").hidden = false;
  $("#account-label").hidden = true;
  $("#logout-button").hidden = true;
  $("#login-message").textContent = message;
}

function valueLabel(value) {
  return ({ PENDING: "Pendente", VERIFIED: "Verificado", BLOCKED: "Bloqueado" })[value] || "Desconhecido";
}

function navigate(viewId) {
  if (["audit-view", "users-view"].includes(viewId) && state.account?.role !== "ADMIN") viewId = "monitor-view";
  if (!["monitor-view", "sources-view", "audit-view", "users-view"].includes(viewId)) return;
  state.view = viewId;
  for (const view of document.querySelectorAll(".app-view")) view.hidden = view.id !== viewId;
  for (const button of document.querySelectorAll(".nav-button")) {
    const active = button.dataset.view === viewId;
    button.classList.toggle("active", active);
    if (active) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  }
  if (viewId === "monitor-view") requestAnimationFrame(() => window.StormTrackMap.resize());
  if (viewId === "sources-view") { refreshProducts(); refreshConnectors(); }
  if (viewId === "audit-view") refreshLogs();
  if (viewId === "users-view") window.StormTrackUsers.refresh();
}

function makeGateSelect(field, value) {
  const label = document.createElement("label");
  label.append(document.createTextNode(gateNames.find(([key]) => key === field)[1]));
  const select = document.createElement("select");
  select.name = field;
  for (const optionValue of gateOptions) {
    const option = document.createElement("option");
    option.value = optionValue;
    option.textContent = valueLabel(optionValue);
    option.selected = value === optionValue;
    select.append(option);
  }
  label.append(select);
  return label;
}

function renderProduct(product) {
  const card = document.createElement("article");
  card.className = "source-card";
  const header = document.createElement("div");
  header.className = "source-card-header";
  const titleBlock = document.createElement("div");
  const title = document.createElement("h3");
  title.textContent = product.product_code;
  const provider = document.createElement("div");
  provider.className = "provider";
  provider.textContent = `${product.source_name} · ${product.provider_code}`;
  titleBlock.append(title, provider);
  const enabled = document.createElement("span");
  enabled.className = product.enabled ? "enabled-badge" : "disabled-badge";
  enabled.textContent = product.enabled ? "Produto liberado no gate" : "Aguardando liberação";
  header.append(titleBlock, enabled);
  card.append(header);

  const grid = document.createElement("div");
  grid.className = "gate-grid";
  for (const [field] of gateNames) {
    if (state.account.role === "ADMIN") grid.append(makeGateSelect(field, product[field]));
    else {
      const cell = document.createElement("div");
      cell.className = "read-only-gate";
      cell.textContent = `${gateNames.find(([key]) => key === field)[1]}: ${valueLabel(product[field])}`;
      grid.append(cell);
    }
  }
  if (state.account.role !== "ADMIN") card.append(grid);

  if (state.account.role === "ADMIN") {
    const form = document.createElement("form");
    form.className = "admin-controls";
    const evidenceLabel = document.createElement("label");
    evidenceLabel.textContent = "Referência de evidência/termos";
    const evidence = document.createElement("input");
    evidence.name = "terms_reference";
    evidence.maxLength = 500;
    evidence.value = product.terms_reference || "";
    evidence.placeholder = "Obrigatória para estados verificados";
    evidenceLabel.append(evidence);
    const evidenceRow = document.createElement("div");
    evidenceRow.className = "evidence-row";
    evidenceRow.append(evidenceLabel);
    const enableLabel = document.createElement("label");
    const enable = document.createElement("input");
    enable.type = "checkbox";
    enable.name = "enabled";
    enable.checked = product.enabled;
    enableLabel.append(enable, document.createTextNode("Liberar este produto para o coletor local (requer ativação da configuração do sistema)"));
    const save = document.createElement("button");
    save.type = "submit";
    save.className = "button button-secondary";
    save.textContent = "Salvar gates";
    evidenceRow.append(save);
    form.append(grid.cloneNode(true), evidenceRow, enableLabel);
    form.addEventListener("submit", async event => {
      event.preventDefault();
      const payload = {};
      for (const [field] of gateNames) payload[field] = $( `select[name="${field}"]`, form).value;
      payload.terms_reference = evidence.value.trim() || null;
      payload.enabled = enable.checked;
      save.disabled = true;
      try {
        await api(`/api/admin/source-products/${product.id}`, { method: "PATCH", body: JSON.stringify(payload) });
        await refreshProducts();
      } catch (error) {
        window.alert(`Não foi possível salvar: ${error.message}`);
      } finally { save.disabled = false; }
    });
    card.append(form);
  }
  return card;
}

async function refreshProducts() {
  const list = $("#source-list");
  list.replaceChildren();
  try {
    const products = await api("/api/source-products");
    $("#product-count").textContent = String(products.length);
    const enabledCount = products.filter(product => product.enabled).length;
    $("#enabled-count").textContent = String(enabledCount);
    $("#collection-state").textContent = enabledCount
      ? `${enabledCount} produto(s) com gates habilitados. Confira o estado do worker e da última coleta; isso não confirma dados atuais.`
      : "Fontes candidatas cadastradas; coleta desabilitada ou aguardando os gates do produto.";
    $("#glm-layer-state").textContent = products.some(product => product.provider_code === "NOAA" && product.product_code === "GLM-L2-LCFA" && product.enabled)
      ? "gates habilitados; aguardando observações"
      : "pendente / coleta desligada";
    if (products.length === 0) {
      const empty = document.createElement("div");
      empty.className = "empty-state";
      empty.textContent = "Nenhum produto cadastrado. Produtos novos começam pendentes e desabilitados.";
      list.append(empty);
    } else {
      for (const product of products) list.append(renderProduct(product));
    }
  } catch (error) {
    list.textContent = error.status === 401 ? "Sessão expirada. Entre novamente." : `Falha ao carregar produtos: ${error.message}`;
    if (error.status === 401) showLogin("Sua sessão expirou. Entre novamente.");
  }
}

function satelliteTimestampLabel(value) {
  if (!value) return "Horário da imagem indisponível";
  return `Imagem observada em ${value.replace("T", " ").replace("Z", " UTC")}`;
}

async function showSatelliteFrame(index) {
  if (!state.satelliteFrames.length) return;
  const safeIndex = Math.max(0, Math.min(index, state.satelliteFrames.length - 1));
  const selected = state.satelliteFrames[safeIndex];
  const slider = $("#satellite-slider");
  const image = $("#satellite-image");
  const empty = $("#satellite-empty");
  state.selectedSatelliteFrame = safeIndex;
  slider.value = String(safeIndex);
  $("#satellite-frame-time").textContent = satelliteTimestampLabel(selected.observed_at_utc);
  $("#satellite-newer").disabled = safeIndex === 0;
  $("#satellite-older").disabled = safeIndex >= state.satelliteFrames.length - 1;
  empty.hidden = false;
  empty.textContent = "Carregando imagem...";
  image.hidden = true;
  try {
    const response = await fetch(selected.image_path, { headers: authHeaders() });
    if (!response.ok) {
      const error = new Error(`Imagem indisponível (${response.status})`);
      error.status = response.status;
      throw error;
    }
    const blob = await response.blob();
    if (state.satelliteObjectUrl) URL.revokeObjectURL(state.satelliteObjectUrl);
    state.satelliteObjectUrl = URL.createObjectURL(blob);
    image.src = state.satelliteObjectUrl;
    image.hidden = false;
    empty.hidden = true;
  } catch (error) {
    empty.hidden = false;
    empty.textContent = error.message;
    if (error.status === 401) showLogin("Sua sessão expirou. Entre novamente.");
  }
}

async function refreshSatelliteFrames() {
  const badge = $("#satellite-state");
  badge.className = "status-pill status-loading";
  badge.textContent = "Consultando imagens NOAA...";
  try {
    const manifest = await api("/api/satellite/goes19/abi/frames?limit=12");
    state.satelliteFrames = manifest.frames || [];
    $("#satellite-credit").textContent = manifest.attribution || "Crédito: CIRA/NOAA";
    const slider = $("#satellite-slider");
    slider.max = String(Math.max(0, state.satelliteFrames.length - 1));
    slider.disabled = state.satelliteFrames.length < 2;
    if (!state.satelliteFrames.length) throw new Error("A fonte não retornou imagens recentes.");
    const ageMinutes = Math.floor((manifest.latest_frame_age_seconds || 0) / 60);
    badge.className = `status-pill ${manifest.source_status === "AVAILABLE" ? "status-ok" : "status-error"}`;
    badge.textContent = manifest.source_status === "AVAILABLE"
      ? `Imagens NOAA no painel · quadro mais recente há ${ageMinutes} min`
      : `Fonte NOAA atrasada · quadro mais recente há ${ageMinutes} min`;
    await showSatelliteFrame(0);
  } catch (error) {
    badge.className = "status-pill status-error";
    badge.textContent = "Imagens NOAA indisponíveis";
    $("#satellite-image").hidden = true;
    $("#satellite-empty").hidden = false;
    $("#satellite-empty").textContent = error.message;
    if (error.status === 401) showLogin("Sua sessão expirou. Entre novamente.");
  }
}

async function refreshConnectors() {
  const list = $("#connector-list");
  if (!list) return;
  list.replaceChildren();
  try {
    const connectors = await api("/api/connectors");
    for (const connector of connectors) {
      const card = document.createElement("article");
      card.className = "connector-card";
      const heading = document.createElement("div");
      heading.className = "source-card-header";
      const title = document.createElement("strong");
      title.textContent = `${connector.provider_code} · ${connector.product_code}`;
      const stateBadge = document.createElement("span");
      stateBadge.className = "disabled-badge";
      stateBadge.textContent = connector.status === "DIRECT_IN_APP_IMAGES_ACTIVE_NO_ARCHIVE"
        ? "Imagem pública no app; sem arquivo local"
        : connector.status === "VIEWER_AVAILABLE_INGESTION_PENDING"
          ? "Visualizador público; ingestão pendente"
          : connector.status === "ADAPTER_IMPLEMENTED_NOT_CONNECTED"
          ? "Adaptador implementado; desconectado"
          : "Estrutura preparada; perfil pendente";
      heading.append(title, stateBadge);
      const name = document.createElement("p");
      name.className = "provider";
      name.textContent = connector.source_name;
      const requirements = document.createElement("p");
      requirements.className = "small muted";
      requirements.textContent = `Próximos itens: ${(connector.required_profile || []).join(", ")}.`;
      card.append(heading, name, requirements);
      list.append(card);
    }
  } catch (error) {
    list.textContent = error.status === 401 ? "Sessão expirada. Entre novamente." : `Falha ao consultar conectores: ${error.message}`;
  }
}

function renderObservationMap(collection) {
  window.StormTrackMap.updateObservations(collection);
}

async function refreshObservations() {
  try {
    renderObservationMap(await api("/api/observations/geojson"));
  } catch (error) {
    if (error.status === 401) return showLogin("Sua sessão expirou. Entre novamente.");
    window.StormTrackMap.clearObservations();
    $("#map-state").className = "status-pill status-error";
    $("#data-updated").textContent = "Observa\u00e7\u00f5es indispon\u00edveis";
    $("#map-state").textContent = "API de observações indisponível";
    $("#map-empty").textContent = "Não foi possível consultar as observações armazenadas.";
    $("#map-empty").hidden = false;
  }
}

async function refreshIngestion() {
  try {
    const runs = await api("/api/ingestion/runs?limit=1");
    if (runs.length) $("#collector-health").textContent = `${runs[0].status} · ${runs[0].finished_at}`;
  } catch (_) {
    $("#collector-health").textContent = "Estado indisponível";
  }
}

async function refreshAnalysisStatus() {
  try {
    const readiness = await api("/api/analysis/status");
    $("#cells-count").textContent = "\u2014";
    $("#cells-title").textContent = "Detecção automática indisponível";
    $("#cells-description").textContent = readiness.cell_detection?.reason || readiness.reason;
    $("#cell-method-state").textContent = "Pendente";
    $("#cells-footnote").textContent = "Aguardando fonte meteorológica e validação do método";
  } catch (error) {
    $("#cells-count").textContent = "\u2014";
    $("#cells-title").textContent = "Estado da detecção indisponível";
    $("#cells-description").textContent = "Não foi possível consultar o estado da detecção.";
    $("#cell-method-state").textContent = "Indisponível";
    if (error.status === 401) showLogin("Sua sessão expirou. Entre novamente.");
  }
}

async function refreshLogs() {
  const list = $("#logs-list");
  list.replaceChildren();
  try {
    const logs = await api("/api/admin/operation-logs?limit=100");
    if (!logs.length) { list.textContent = "Ainda não há operações registradas."; return; }
    for (const log of logs) {
      const row = document.createElement("div");
      row.className = "log-row";
      const time = document.createElement("time");
      time.textContent = log.occurred_at;
      const event = document.createElement("strong");
      event.textContent = log.event_code;
      const details = document.createElement("span");
      details.textContent = log.details;
      row.append(time, event, details);
      list.append(row);
    }
  } catch (error) { list.textContent = `Falha ao carregar logs: ${error.message}`; }
}

$("#login-form").addEventListener("submit", async event => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = $("button[type=submit]", form);
  button.disabled = true;
  $("#login-message").textContent = "Verificando credenciais…";
  const formData = new FormData(form);
  try {
    const result = await api("/api/auth/login", { method: "POST", body: JSON.stringify({ username: formData.get("username"), password: formData.get("password") }) });
    state.token = result.access_token;
    sessionStorage.setItem("stormtrack_token", state.token);
    form.reset();
    showDashboard(result.account);
    await refreshHealth();
  } catch (error) { $("#login-message").textContent = error.message; }
  finally { button.disabled = false; }
});

$("#logout-button").addEventListener("click", async () => {
  try { await api("/api/auth/logout", { method: "POST" }); } catch (_) { /* Local session is cleared even if the server is unreachable. */ }
  showLogin("Sessão encerrada.");
});

$("#create-source-form").addEventListener("submit", async event => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = $("button[type=submit]", form);
  button.disabled = true;
  const data = new FormData(form);
  const payload = Object.fromEntries(data.entries());
  payload.terms_reference = payload.terms_reference.trim() || null;
  try {
    await api("/api/admin/source-products", { method: "POST", body: JSON.stringify(payload) });
    form.reset();
    $("#source-message").textContent = "Produto cadastrado pendente e desabilitado.";
    await refreshProducts();
  } catch (error) { $("#source-message").textContent = error.message; }
  finally { button.disabled = false; }
});

$("#refresh-button").addEventListener("click", refreshProducts);
$("#connectors-refresh").addEventListener("click", refreshConnectors);
$("#satellite-refresh").addEventListener("click", refreshSatelliteFrames);
$("#satellite-slider").addEventListener("input", event => showSatelliteFrame(Number(event.currentTarget.value)));
$("#satellite-newer").addEventListener("click", () => showSatelliteFrame(0));
$("#satellite-older").addEventListener("click", () => showSatelliteFrame(state.selectedSatelliteFrame + 1));
$("#logs-button").addEventListener("click", refreshLogs);
for (const button of document.querySelectorAll("[data-view]")) {
  button.addEventListener("click", () => navigate(button.dataset.view));
}
for (const button of document.querySelectorAll("[data-open-view]")) {
  button.addEventListener("click", () => navigate(button.dataset.openView));
}

async function initialize() {
  renderObservationMap({ features: [] });
  await refreshHealth();
  if (!state.token) return;
  try { showDashboard(await api("/api/auth/me")); }
  catch (_) { showLogin("Sessão inválida ou expirada. Entre novamente."); }
}
initialize();
