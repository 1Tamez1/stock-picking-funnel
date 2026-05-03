const state = {
  view: "dashboard",
  bootstrap: null,
  templateLibrary: null,
  activeStageId: null,
  sidebarCollapsed: false,
  currentCompany: null,
  currentReport: null,
  companyList: {
    search: "",
    statusFilter: "all",
    order: "updated_desc",
    page: 1,
    perPage: 50,
  },
  reportList: {
    search: "",
    stageFilter: "all",
    resultFilter: "all",
    order: "completed_desc",
    includeDrafts: false,
    page: 1,
    perPage: 50,
  },
  selectedTemplateId: undefined,
  selectedTemplateStageId: null,
  fieldSources: {},
  fieldNotes: {},
  fieldExceptions: {},
  completionPreview: null,
  activeFieldId: null,
  activeFieldLabel: "",
  pendingDeleteSourceId: null,
  documentStatusPoll: null,
};

const SOURCE_TYPES = [
  "Annual report",
  "Quarterly report",
  "Investor presentation",
  "Investor day",
  "Proxy / compensation filing",
  "Earnings call",
  "Competitor filing",
  "Industry source",
  "News / secondary source",
  "Dataset",
  "Other",
];

const EVIDENCE_GRADES = [
  ["F", "Audited, reported, or directly filed fact"],
  ["O", "Observable operating, customer, competitive, or industry evidence"],
  ["M", "Management claim"],
  ["I", "Analyst inference"],
  ["V", "Item to verify later"],
];

const DEFAULT_FINAL_DECISIONS = [
  ["Pass", "Proceed to Next Step"],
  ["Watchlist", "Watchlist"],
  ["Archive", "Archive"],
];

const FIELD_EXCEPTION_OPTIONS = [
  ["", "No exception"],
  ["unknown", "Unknown after investigation"],
  ["not_disclosed", "Not disclosed by source"],
  ["not_applicable", "Not applicable for this company"],
];

const COMPACT_TEXTAREA_SECTIONS = new Set([
  "1. Business In Plain English",
  "2. Why Is This Stock On The Desk?",
  "Moat Hypothesis",
  "5. Market Expectations Check",
  "1. Inversion",
  "One-Page Screening Conclusion",
]);

const content = document.querySelector("#content");
const statusEl = document.querySelector("#status");
const titleEl = document.querySelector("#view-title");
const eyebrowEl = document.querySelector("#view-eyebrow");

document.addEventListener("DOMContentLoaded", init);

async function init() {
  const storedSidebarState = window.localStorage?.getItem("sidebar-collapsed");
  state.sidebarCollapsed = storedSidebarState === null ? true : storedSidebarState === "1";
  bindGlobalEvents();
  applySidebarState();
  await refreshBootstrap();
  renderView("dashboard");
}

function bindGlobalEvents() {
  document.querySelectorAll(".nav-button").forEach((button) => {
    if (!button.dataset.view) return;
    button.addEventListener("click", () => {
      renderView(button.dataset.view);
      closeSidebar();
    });
  });
  document.querySelectorAll("#main-sidebar-toggle, #drawer-sidebar-toggle").forEach((button) => {
    button.addEventListener("click", toggleSidebar);
  });
  document.querySelector("#sidebar-backdrop").addEventListener("click", closeSidebar);
  document.querySelector("#settings-button").addEventListener("click", () => {
    openSettingsDialog();
  });
  document.querySelectorAll("[data-close-settings]").forEach((button) => {
    button.addEventListener("click", closeSettingsDialog);
  });
  document.querySelector("#settings-dialog").addEventListener("click", (event) => {
    if (event.target === event.currentTarget) closeSettingsDialog();
  });
  document.querySelector("#company-form").addEventListener("submit", createCompanyFromDialog);
  window.addEventListener("scroll", syncSidebarToggleAlignment, { passive: true });
  window.addEventListener("resize", syncSidebarToggleAlignment);
  syncSidebarToggleAlignment();
}

function syncSidebarToggleAlignment() {
  document.body.classList.toggle("page-at-top", window.scrollY <= 4);
  const mainToggle = document.querySelector("#main-sidebar-toggle");
  if (!mainToggle) return;
  const rect = mainToggle.getBoundingClientRect();
  document.documentElement.style.setProperty("--drawer-toggle-anchor-top", `${Math.round(rect.top)}px`);
  document.documentElement.style.setProperty("--drawer-toggle-anchor-left", `${Math.round(rect.left)}px`);
  document.documentElement.style.setProperty("--drawer-toggle-anchor-width", `${Math.round(rect.width)}px`);
  document.documentElement.style.setProperty("--drawer-toggle-anchor-height", `${Math.round(rect.height)}px`);
}

function applySidebarState() {
  const isOpen = !state.sidebarCollapsed;
  document.body.classList.toggle("sidebar-collapsed", state.sidebarCollapsed);
  document.body.classList.toggle("sidebar-open", isOpen);
  document.querySelectorAll("#main-sidebar-toggle, #drawer-sidebar-toggle").forEach((button) => {
    button.setAttribute("aria-expanded", String(isOpen));
  });
  document.querySelector("#sidebar-backdrop").setAttribute("aria-hidden", String(!isOpen));
  window.requestAnimationFrame(syncSidebarToggleAlignment);
}

function setSidebarCollapsed(collapsed) {
  state.sidebarCollapsed = Boolean(collapsed);
  window.localStorage?.setItem("sidebar-collapsed", state.sidebarCollapsed ? "1" : "0");
  applySidebarState();
}

function toggleSidebar() {
  setSidebarCollapsed(!state.sidebarCollapsed);
}

function closeSidebar() {
  if (state.sidebarCollapsed) return;
  setSidebarCollapsed(true);
}

async function api(path, options = {}) {
  const headers = options.body instanceof FormData ? {} : { "Content-Type": "application/json" };
  const response = await fetch(path, { ...options, headers: { ...headers, ...(options.headers || {}) } });
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) {
    const message = payload && payload.error ? payload.error : `Request failed: ${response.status}`;
    const error = new Error(message);
    error.status = response.status;
    error.payload = payload;
    throw error;
  }
  return payload;
}

function clearDocumentStatusPolling() {
  if (state.documentStatusPoll?.timer) window.clearTimeout(state.documentStatusPoll.timer);
  state.documentStatusPoll = null;
}

function currentPendingDocumentIds() {
  const ids = new Set();
  const collectDocument = (document) => {
    if (document && Number(document.id) && document.normalized_status === "pending") ids.add(Number(document.id));
  };
  const collectSource = (source) => {
    if (source && Number(source.document_id) && source.capture_state === "pending") ids.add(Number(source.document_id));
  };
  [...(state.currentCompany?.documents || []), ...(state.currentReport?.documents || [])].forEach(collectDocument);
  [
    ...(state.currentCompany?.company_sources || []),
    ...(state.currentReport?.sources || []),
    ...(state.currentReport?.company_sources || []),
    ...(state.currentReport?.suggested_sources || []),
  ].forEach(collectSource);
  return [...ids];
}

function sourceReasonForState(source) {
  const status = source.capture_state || source.reusability_status || "pending";
  if (status === "ready") return "Stored artifact and normalized LLM view available.";
  if (status === "limited") return "Stored artifact saved, but normalized text is limited. Verify against the original file.";
  if (status === "pending") return "Stored artifact saved. Normalized LLM view is still pending.";
  if (status === "failed") return source.capture_error || "Stored artifact saved, but normalization failed. Use the original file for verification.";
  if (status === "link_only") return "URL saved without snapshot; citeable, but not reliably reusable by later stages.";
  return source.reusability_reason || "";
}

function applyDocumentStatusUpdate(document) {
  if (!document?.id) return;
  const updateDocument = (item) => {
    if (!item || Number(item.id) !== Number(document.id)) return;
    Object.assign(item, document);
  };
  const updateSource = (source) => {
    if (!source || Number(source.document_id) !== Number(document.id)) return;
    source.normalized_status = document.normalized_status;
    source.normalized_format = document.normalized_format;
    source.normalized_method = document.normalized_method;
    source.normalized_notes = document.normalized_notes;
    source.normalized_preview = document.normalized_preview;
    source.normalized_text_path = document.normalized_text_path;
    source.normalized_available = Boolean(document.normalized_available);
    source.capture_state = document.normalized_status;
    source.capture_error = document.normalized_status === "failed" ? (document.normalized_notes || "") : "";
    source.document_status_url = document.status_url || source.document_status_url || "";
    source.document_normalized_url = document.normalized_url || "";
    source.reusability_status = source.capture_state;
    source.reusability_reason = sourceReasonForState(source);
  };
  [...(state.currentCompany?.documents || []), ...(state.currentReport?.documents || [])].forEach(updateDocument);
  [
    ...(state.currentCompany?.company_sources || []),
    ...(state.currentReport?.sources || []),
    ...(state.currentReport?.company_sources || []),
    ...(state.currentReport?.suggested_sources || []),
  ].forEach(updateSource);
}

function queueDocumentStatusPolling(contextLabel = "Document") {
  clearDocumentStatusPolling();
  const documentIds = currentPendingDocumentIds();
  if (!documentIds.length) return;
  const poll = async () => {
    const results = await Promise.all(
      state.documentStatusPoll.ids.map(async (documentId) => {
        try {
          return (await api(`/api/documents/${documentId}/status`)).document;
        } catch (error) {
          return null;
        }
      }),
    );
    const nextPending = [];
    let completed = 0;
    results.forEach((document) => {
      if (!document) return;
      applyDocumentStatusUpdate(document);
      if (document.normalized_status === "pending") nextPending.push(Number(document.id));
      else completed += 1;
    });
    if (!nextPending.length) {
      clearDocumentStatusPolling();
      if (completed) status(`${contextLabel} processing finished. Latest preview links are ready.`, false);
      return;
    }
    state.documentStatusPoll = {
      ...state.documentStatusPoll,
      ids: nextPending,
      timer: window.setTimeout(poll, 4000),
    };
  };
  state.documentStatusPoll = {
    ids: documentIds,
    label: contextLabel,
    timer: window.setTimeout(poll, 4000),
  };
}

async function refreshBootstrap() {
  state.bootstrap = await api("/api/bootstrap");
}

async function loadTemplateLibrary(force = false) {
  if (!force && Array.isArray(state.templateLibrary)) return state.templateLibrary;
  state.templateLibrary = (await api("/api/templates")).templates || [];
  return state.templateLibrary;
}

async function loadTemplateDetail(templateId) {
  if (!templateId) return null;
  return (await api(`/api/templates/${templateId}`)).template;
}

function openTemplateEditorForStage(stageId, fallbackTemplateId = null) {
  state.selectedTemplateStageId = Number(stageId) || null;
  state.selectedTemplateId = Number(fallbackTemplateId || 0) || null;
  closeSettingsDialog();
  renderView("templates");
}

function renderView(view) {
  const labels = {
    dashboard: ["Research Control", "Dashboard"],
    pool: ["Research Universe", "All Companies"],
    funnel: ["Active Research", "Funnel"],
    reports: ["Cross-Company Research", "Reports"],
    monitoring: ["Rules and Alerts", "Monitoring"],
    watchlist: ["Deferred Candidates", "Watchlist"],
    archive: ["Rejected or Paused", "Archive"],
    templates: ["Editable Research Forms", "Templates"],
  };
  const nextView = labels[view] ? view : "dashboard";
  state.view = nextView;
  clearDocumentStatusPolling();
  document.querySelectorAll(".nav-button").forEach((button) => {
    button.classList.toggle("active", button.dataset.view === nextView);
  });
  status("");
  eyebrowEl.textContent = labels[nextView][0];
  titleEl.textContent = labels[nextView][1];
  if (nextView === "dashboard") renderDashboard();
  if (nextView === "pool") renderAllCompanies();
  if (nextView === "funnel") renderFunnel();
  if (nextView === "reports") renderReports();
  if (nextView === "monitoring") renderMonitoring();
  if (nextView === "watchlist") renderCompanyBucket("watchlist");
  if (nextView === "archive") renderCompanyBucket("archive");
  if (nextView === "templates") renderTemplates();
}

function openSettingsDialog() {
  closeSidebar();
  const dialog = document.querySelector("#settings-dialog");
  if (!dialog.open) dialog.showModal();
  renderSettingsDialog();
}

function closeSettingsDialog() {
  const dialog = document.querySelector("#settings-dialog");
  if (dialog?.open) dialog.close();
}

function settingsOverviewMarkup() {
  const summary = state.bootstrap?.settings_summary || {};
  return `
    <section class="metric-grid settings-summary-grid">
      ${metricCard("Reports Created", Number(summary.reports_created_total || 0), "reports")}
      ${metricCard("Sources Uploaded", Number(summary.sources_uploaded_total || 0), "sources")}
      ${metricCard("Companies Outside Pool", Number(summary.companies_outside_pool_total || 0), "outside-pool")}
    </section>
    <div class="button-row settings-actions">
      <button class="secondary" type="button" data-open-settings-templates="1">Open Templates</button>
    </div>
  `;
}

function renderSettingsDialog() {
  const panel = document.querySelector("#settings-panel");
  if (!panel) return;
  panel.innerHTML = settingsOverviewMarkup();
  panel.querySelector("[data-open-settings-templates]")?.addEventListener("click", () => {
    closeSettingsDialog();
    renderView("templates");
  });
}

function renderDashboard() {
  const dashboard = state.bootstrap.dashboard;
  content.innerHTML = `
    <section class="metric-grid">
      ${dashboard.buckets.map((bucket) => metricCard(bucket.name, bucket.count, bucket.key)).join("")}
    </section>
    <section class="panel">
      <div class="panel-header">
        <div>
          <h3>Funnel Position</h3>
          <p class="muted">Use the funnel counts as the main operating view for active research.</p>
        </div>
      </div>
      <div class="panel-body pipeline">
        ${dashboard.stages.map((stage, index) => `
          <button class="stage-tile" data-stage-filter="${stage.id}">
            <div class="stage-tile-head">
              <span class="stage-order">Stage ${String(stage.sequence || index + 1).padStart(2, "0")}</span>
              <span class="pill ${stage.count ? "green" : ""}">${stage.count} active</span>
            </div>
            <div class="stage-tile-copy">
              <strong>${escapeHtml(stage.name)}</strong>
              <span class="muted">${escapeHtml(stage.description || "Open the stage view for the active company list.")}</span>
            </div>
            <div class="stage-tile-metrics">
              <div>
                <strong>${stage.count}</strong>
                <span>Companies</span>
              </div>
              <div>
                <strong>${stage.completed_reports}</strong>
                <span>Completed Reports</span>
              </div>
            </div>
          </button>
        `).join("")}
      </div>
    </section>
    <section class="panel">
      <div class="panel-header">
        <div>
          <h3>Triggered Monitoring Rules</h3>
          <p class="muted">Objective rules that currently meet their threshold.</p>
        </div>
      </div>
      <div class="panel-body">
        ${dashboard.alerts.length ? alertList(dashboard.alerts) : `<div class="empty-state">No active alerts.</div>`}
      </div>
    </section>
  `;
  content.querySelectorAll("[data-bucket-shortcut]").forEach((button) => {
    button.addEventListener("click", () => {
      const key = button.dataset.bucketShortcut;
      renderView(key === "pool" ? "pool" : key);
    });
  });
  content.querySelectorAll("[data-stage-filter]").forEach((button) => {
    button.addEventListener("click", () => {
      state.activeStageId = Number(button.dataset.stageFilter);
      renderView("funnel");
    });
  });
}

function metricCard(label, count, key) {
  const color = key === "archive" ? "red" : key === "watchlist" ? "amber" : key === "monitoring" ? "cyan" : "green";
  return `
    <button class="metric-card" data-bucket-shortcut="${key}">
      <strong>${count}</strong>
      <span class="pill ${color}">${escapeHtml(label)}</span>
    </button>
  `;
}

async function renderCompanyBucket(bucket) {
  const data = await api(`/api/companies?bucket=${encodeURIComponent(bucket)}`);
  const heading = state.bootstrap.buckets.find((item) => item.key === bucket)?.name || bucket;
  content.innerHTML = `
    <section class="panel">
      <div class="panel-header">
        <div>
          <h3>${escapeHtml(heading)}</h3>
          <p class="muted">${bucketHelp(bucket)}</p>
        </div>
        ${bucket === "pool" ? `<button class="secondary" data-open-add>Add Company</button>` : ""}
      </div>
      <div class="panel-body">
        ${companyTable(data.companies, bucket)}
      </div>
    </section>
  `;
  bindCompanyTable();
  bindCompanyRowExpanders();
  content.querySelector("[data-open-add]")?.addEventListener("click", openCompanyDialog);
}

function bucketHelp(bucket) {
  if (bucket === "watchlist") return "Promising companies waiting on price, evidence, or reassessment conditions.";
  if (bucket === "archive") return "Companies with red flags or failed gates, with reassessment notes visible here.";
  return "Companies in this category.";
}

function allCompaniesHelp() {
  return "Search, filter, and page through the full research universe without losing track of funnel, watchlist, or archive positions.";
}

function allCompaniesQueryString() {
  const params = new URLSearchParams();
  if (state.companyList.statusFilter && state.companyList.statusFilter !== "all") {
    params.set("bucket", state.companyList.statusFilter);
  }
  if (state.companyList.search.trim()) params.set("search", state.companyList.search.trim());
  params.set("order", state.companyList.order);
  params.set("page", String(state.companyList.page));
  params.set("per_page", String(state.companyList.perPage));
  return `/api/companies?${params.toString()}`;
}

async function renderAllCompanies() {
  const data = await api(allCompaniesQueryString());
  const totalPages = Math.max(1, Math.ceil(Number(data.total || 0) / Number(data.per_page || state.companyList.perPage || 50)));
  const start = Number(data.total) ? ((Number(data.page || 1) - 1) * Number(data.per_page || state.companyList.perPage) + 1) : 0;
  const end = Number(data.total) ? Math.min(Number(data.total), start + Number(data.companies.length || 0) - 1) : 0;
  content.innerHTML = `
    <section class="panel">
      <div class="panel-header">
        <div>
          <h3>All Companies</h3>
          <p class="muted">${allCompaniesHelp()}</p>
        </div>
        <button class="secondary" data-open-add>Add Company</button>
      </div>
      <div class="panel-body grid">
        ${allCompaniesToolbar()}
        ${companyTable(data.companies, "pool", { summaryHeading: "Latest Report / Summary" })}
        ${allCompaniesPagination(start, end, Number(data.total || 0), totalPages)}
      </div>
    </section>
  `;
  bindAllCompaniesControls(totalPages);
  bindCompanyTable();
  bindCompanyRowExpanders();
  content.querySelector("[data-open-add]")?.addEventListener("click", openCompanyDialog);
}

function allCompaniesToolbar() {
  const statusOptions = [
    `<option value="all"${state.companyList.statusFilter === "all" ? " selected" : ""}>All statuses</option>`,
    ...state.bootstrap.buckets.map((bucket) => `<option value="${escapeAttr(bucket.key)}"${state.companyList.statusFilter === bucket.key ? " selected" : ""}>${escapeHtml(bucket.name)}</option>`),
  ].join("");
  return `
    <form class="list-toolbar" id="all-companies-toolbar">
      <label class="toolbar-search">Search
        <input name="search" value="${escapeAttr(state.companyList.search)}" placeholder="Ticker or company name" />
      </label>
      <label>Status
        <select name="status_filter">${statusOptions}</select>
      </label>
      <label>Order
        <select name="order">
          <option value="updated_desc"${state.companyList.order === "updated_desc" ? " selected" : ""}>Recently updated</option>
          <option value="ticker_asc"${state.companyList.order === "ticker_asc" ? " selected" : ""}>Ticker A-Z</option>
          <option value="ticker_desc"${state.companyList.order === "ticker_desc" ? " selected" : ""}>Ticker Z-A</option>
          <option value="name_asc"${state.companyList.order === "name_asc" ? " selected" : ""}>Company A-Z</option>
          <option value="review_date_asc"${state.companyList.order === "review_date_asc" ? " selected" : ""}>Nearest review date</option>
          <option value="review_date_desc"${state.companyList.order === "review_date_desc" ? " selected" : ""}>Latest review date</option>
          <option value="status_asc"${state.companyList.order === "status_asc" ? " selected" : ""}>Status</option>
        </select>
      </label>
      <div class="toolbar-actions">
        <button class="secondary" type="submit">Apply</button>
        <button class="secondary" type="button" id="all-companies-reset">Reset</button>
      </div>
    </form>
  `;
}

function allCompaniesPagination(start, end, total, totalPages) {
  return `
    <div class="pagination-bar">
      <span class="muted">${total ? `${start}-${end} of ${total} companies` : "0 companies"}</span>
      <div class="button-row pagination-actions">
        <label>Rows
          <select id="all-companies-per-page">
            ${[25, 50, 100, 200].map((value) => `<option value="${value}"${Number(state.companyList.perPage) === value ? " selected" : ""}>${value}</option>`).join("")}
          </select>
        </label>
        <button class="small-button" type="button" id="all-companies-prev"${state.companyList.page <= 1 ? " disabled" : ""}>Back</button>
        <span class="muted">Page ${state.companyList.page} of ${totalPages}</span>
        <button class="small-button" type="button" id="all-companies-next"${state.companyList.page >= totalPages ? " disabled" : ""}>Next</button>
      </div>
    </div>
  `;
}

function bindAllCompaniesControls(totalPages) {
  const toolbar = content.querySelector("#all-companies-toolbar");
  toolbar?.addEventListener("submit", (event) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    state.companyList.search = String(form.get("search") || "");
    state.companyList.statusFilter = String(form.get("status_filter") || "all");
    state.companyList.order = String(form.get("order") || "updated_desc");
    state.companyList.page = 1;
    renderAllCompanies();
  });
  content.querySelector("#all-companies-reset")?.addEventListener("click", () => {
    state.companyList = { search: "", statusFilter: "all", order: "updated_desc", page: 1, perPage: 50 };
    renderAllCompanies();
  });
  content.querySelector("#all-companies-per-page")?.addEventListener("change", (event) => {
    state.companyList.perPage = Number(event.currentTarget.value || 50);
    state.companyList.page = 1;
    renderAllCompanies();
  });
  content.querySelector("#all-companies-prev")?.addEventListener("click", () => {
    state.companyList.page = Math.max(1, state.companyList.page - 1);
    renderAllCompanies();
  });
  content.querySelector("#all-companies-next")?.addEventListener("click", () => {
    state.companyList.page = Math.min(totalPages, state.companyList.page + 1);
    renderAllCompanies();
  });
}

function reportsHelp() {
  return "Review every report across the research system, with summaries visible at a glance and drafts hidden unless you explicitly include them.";
}

function reportsQueryString() {
  const params = new URLSearchParams();
  if (state.reportList.search.trim()) params.set("search", state.reportList.search.trim());
  if (state.reportList.stageFilter && state.reportList.stageFilter !== "all") {
    params.set("stage_id", state.reportList.stageFilter);
  }
  if (state.reportList.resultFilter && state.reportList.resultFilter !== "all") {
    params.set("result", state.reportList.resultFilter);
  }
  if (state.reportList.includeDrafts) params.set("include_drafts", "true");
  params.set("order", state.reportList.order);
  params.set("page", String(state.reportList.page));
  params.set("per_page", String(state.reportList.perPage));
  return `/api/reports?${params.toString()}`;
}

async function renderReports() {
  const requestedView = state.view;
  content.innerHTML = reportsViewMarkup(`<div class="empty-state">Loading reports...</div>`);
  try {
    const data = await loadReportsData();
    if (state.view !== requestedView) return;
    const totalPages = Math.max(1, Math.ceil(Number(data.total || 0) / Number(data.per_page || state.reportList.perPage || 50)));
    const start = Number(data.total) ? ((Number(data.page || 1) - 1) * Number(data.per_page || state.reportList.perPage) + 1) : 0;
    const end = Number(data.total) ? Math.min(Number(data.total), start + Number(data.reports.length || 0) - 1) : 0;
    content.innerHTML = reportsViewMarkup(
      reportListTable(data.reports || []),
      reportsPagination(start, end, Number(data.total || 0), totalPages),
    );
    bindReportsControls(totalPages);
    bindReportTable();
    bindCompanyRowExpanders();
    if (data.compatibilityMode) {
      status("Reports loaded in compatibility mode from company detail data. Restart the app server to enable the direct reports endpoint.");
    }
  } catch (error) {
    if (state.view !== requestedView) return;
    content.innerHTML = reportsViewMarkup(
      `<div class="empty-state">Reports could not be loaded. Refresh the app, and if the server was already running, restart it so the new reports endpoint is available.</div>`,
    );
    bindReportsControls(1);
    status(error.message || "Failed to load reports.", true);
  }
}

function reportsViewMarkup(tableMarkup, paginationMarkup = "") {
  return `
    <section class="panel">
      <div class="panel-header">
        <div>
          <h3>Reports</h3>
          <p class="muted">${reportsHelp()}</p>
        </div>
      </div>
      <div class="panel-body grid">
        ${reportsToolbar()}
        ${tableMarkup}
        ${paginationMarkup}
      </div>
    </section>
  `;
}

async function loadReportsData() {
  try {
    return await api(reportsQueryString());
  } catch (error) {
    if (error?.status !== 404 && error?.payload?.code !== "not_found") throw error;
    return loadLegacyReportsData();
  }
}

async function loadLegacyReportsData() {
  const companies = await fetchAllCompaniesForReports();
  const reports = [];
  for (let index = 0; index < companies.length; index += 12) {
    const batch = companies.slice(index, index + 12);
    const details = await Promise.all(batch.map(async (company) => (await api(`/api/companies/${company.id}`)).company));
    details.forEach((company) => {
      (company.reports || []).forEach((report) => {
        reports.push(normalizeLegacyReportSummary(company, report));
      });
    });
  }
  const filtered = filterReportsList(reports);
  const sorted = filtered.sort(compareReportsForOrder(state.reportList.order));
  const safePage = Math.max(1, Number(state.reportList.page || 1));
  const safePerPage = Math.max(1, Number(state.reportList.perPage || 50));
  const offset = (safePage - 1) * safePerPage;
  return {
    reports: sorted.slice(offset, offset + safePerPage),
    total: sorted.length,
    page: safePage,
    per_page: safePerPage,
    compatibilityMode: true,
  };
}

async function fetchAllCompaniesForReports() {
  const firstPage = await api("/api/companies?order=updated_desc&page=1&per_page=200");
  const companies = [...(firstPage.companies || [])];
  const totalPages = Math.max(1, Math.ceil(Number(firstPage.total || 0) / Number(firstPage.per_page || 200)));
  if (totalPages <= 1) return companies;
  const remainingPages = await Promise.all(
    Array.from({ length: totalPages - 1 }, (_, index) => api(`/api/companies?order=updated_desc&page=${index + 2}&per_page=200`)),
  );
  remainingPages.forEach((page) => companies.push(...(page.companies || [])));
  return companies;
}

function normalizeLegacyReportSummary(company, report) {
  const completedAt = String(report.completed_at || (report.result !== "Draft" ? report.updated_at || "" : "") || "");
  return {
    ...report,
    ticker: company.ticker || "",
    company_name: company.name || "",
    completed_at: completedAt,
  };
}

function filterReportsList(reports) {
  const search = state.reportList.search.trim().toLowerCase();
  return (reports || []).filter((report) => {
    if (!state.reportList.includeDrafts && report.result === "Draft") return false;
    if (state.reportList.stageFilter !== "all" && String(report.stage_id || "") !== String(state.reportList.stageFilter || "")) return false;
    if (state.reportList.resultFilter !== "all" && String(report.result || "") !== String(state.reportList.resultFilter || "")) return false;
    if (!search) return true;
    return reportSearchText(report).includes(search);
  });
}

function reportSearchText(report) {
  return [
    report.ticker,
    report.company_name,
    report.title,
    report.summary,
    report.report_month,
    report.stage_name,
    report.result,
    report.next_action,
  ].filter(Boolean).join(" ").toLowerCase();
}

function reportTimestampValue(value) {
  const timestamp = Date.parse(String(value || ""));
  return Number.isFinite(timestamp) ? timestamp : 0;
}

function reportCompletedValue(report) {
  if (report.completed_at) return reportTimestampValue(report.completed_at);
  if (report.result !== "Draft") return reportTimestampValue(report.updated_at || report.created_at || "");
  return 0;
}

function compareReportsForOrder(order) {
  return (left, right) => {
    if (order === "completed_asc") {
      return reportCompletedValue(left) - reportCompletedValue(right)
        || Number(left.id) - Number(right.id);
    }
    if (order === "updated_desc") {
      return reportTimestampValue(right.updated_at || right.created_at || "") - reportTimestampValue(left.updated_at || left.created_at || "")
        || Number(right.id) - Number(left.id);
    }
    if (order === "updated_asc") {
      return reportTimestampValue(left.updated_at || left.created_at || "") - reportTimestampValue(right.updated_at || right.created_at || "")
        || Number(left.id) - Number(right.id);
    }
    if (order === "company_asc") {
      return String(left.ticker || left.company_name || "").localeCompare(String(right.ticker || right.company_name || ""))
        || String(left.company_name || "").localeCompare(String(right.company_name || ""))
        || Number(right.id) - Number(left.id);
    }
    if (order === "stage_asc") {
      return Number(left.stage_sequence || 999) - Number(right.stage_sequence || 999)
        || reportCompletedValue(right) - reportCompletedValue(left)
        || Number(right.id) - Number(left.id);
    }
    if (order === "result_asc") {
      return String(left.result || "").localeCompare(String(right.result || ""))
        || reportCompletedValue(right) - reportCompletedValue(left)
        || Number(right.id) - Number(left.id);
    }
    if (order === "title_asc") {
      return String(left.title || "").localeCompare(String(right.title || ""))
        || Number(right.id) - Number(left.id);
    }
    return reportCompletedValue(right) - reportCompletedValue(left)
      || Number(right.id) - Number(left.id);
  };
}

function reportsToolbar() {
  const stageOptions = [
    `<option value="all"${state.reportList.stageFilter === "all" ? " selected" : ""}>All stages</option>`,
    ...state.bootstrap.stages.map(
      (stage) => `<option value="${stage.id}"${String(state.reportList.stageFilter) === String(stage.id) ? " selected" : ""}>${escapeHtml(stage.name)}</option>`,
    ),
  ].join("");
  const resultOptions = [
    `<option value="all"${state.reportList.resultFilter === "all" ? " selected" : ""}>All results</option>`,
    ...state.bootstrap.report_actions.map(
      (result) => `<option value="${escapeAttr(result)}"${state.reportList.resultFilter === result ? " selected" : ""}>${escapeHtml(result)}</option>`,
    ),
    ...(state.reportList.includeDrafts
      ? [`<option value="Draft"${state.reportList.resultFilter === "Draft" ? " selected" : ""}>Draft</option>`]
      : []),
  ].join("");
  return `
    <form class="list-toolbar reports-toolbar" id="reports-toolbar">
      <label class="toolbar-search">Search
        <input name="search" value="${escapeAttr(state.reportList.search)}" placeholder="Ticker, company, report title, or summary" />
      </label>
      <label>Stage
        <select name="stage_filter">${stageOptions}</select>
      </label>
      <label>Result
        <select name="result_filter">${resultOptions}</select>
      </label>
      <label>Order
        <select name="order">
          <option value="completed_desc"${state.reportList.order === "completed_desc" ? " selected" : ""}>Recently completed</option>
          <option value="completed_asc"${state.reportList.order === "completed_asc" ? " selected" : ""}>Oldest completed</option>
          <option value="updated_desc"${state.reportList.order === "updated_desc" ? " selected" : ""}>Recently updated</option>
          <option value="updated_asc"${state.reportList.order === "updated_asc" ? " selected" : ""}>Oldest updated</option>
          <option value="company_asc"${state.reportList.order === "company_asc" ? " selected" : ""}>Company A-Z</option>
          <option value="stage_asc"${state.reportList.order === "stage_asc" ? " selected" : ""}>Stage</option>
          <option value="result_asc"${state.reportList.order === "result_asc" ? " selected" : ""}>Result</option>
          <option value="title_asc"${state.reportList.order === "title_asc" ? " selected" : ""}>Report title</option>
        </select>
      </label>
      <div class="toolbar-actions">
        <label class="checkbox-row toolbar-toggle">
          <input type="checkbox" name="include_drafts"${state.reportList.includeDrafts ? " checked" : ""} />
          <span>Include Drafts</span>
        </label>
        <button class="secondary" type="submit">Apply</button>
        <button class="secondary" type="button" id="reports-reset">Reset</button>
      </div>
    </form>
  `;
}

function reportsPagination(start, end, total, totalPages) {
  return `
    <div class="pagination-bar">
      <span class="muted">${total ? `${start}-${end} of ${total} reports` : "0 reports"}</span>
      <div class="button-row pagination-actions">
        <label>Rows
          <select id="reports-per-page">
            ${[25, 50, 100, 200].map((value) => `<option value="${value}"${Number(state.reportList.perPage) === value ? " selected" : ""}>${value}</option>`).join("")}
          </select>
        </label>
        <button class="small-button" type="button" id="reports-prev"${state.reportList.page <= 1 ? " disabled" : ""}>Back</button>
        <span class="muted">Page ${state.reportList.page} of ${totalPages}</span>
        <button class="small-button" type="button" id="reports-next"${state.reportList.page >= totalPages ? " disabled" : ""}>Next</button>
      </div>
    </div>
  `;
}

function bindReportsControls(totalPages) {
  const toolbar = content.querySelector("#reports-toolbar");
  toolbar?.addEventListener("submit", (event) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    state.reportList.search = String(form.get("search") || "");
    state.reportList.stageFilter = String(form.get("stage_filter") || "all");
    state.reportList.resultFilter = String(form.get("result_filter") || "all");
    state.reportList.order = String(form.get("order") || "completed_desc");
    state.reportList.includeDrafts = form.get("include_drafts") === "on";
    if (!state.reportList.includeDrafts && state.reportList.resultFilter === "Draft") {
      state.reportList.resultFilter = "all";
    }
    state.reportList.page = 1;
    renderReports();
  });
  content.querySelector("#reports-reset")?.addEventListener("click", () => {
    state.reportList = {
      search: "",
      stageFilter: "all",
      resultFilter: "all",
      order: "completed_desc",
      includeDrafts: false,
      page: 1,
      perPage: 50,
    };
    renderReports();
  });
  content.querySelector("#reports-per-page")?.addEventListener("change", (event) => {
    state.reportList.perPage = Number(event.currentTarget.value || 50);
    state.reportList.page = 1;
    renderReports();
  });
  content.querySelector("#reports-prev")?.addEventListener("click", () => {
    state.reportList.page = Math.max(1, state.reportList.page - 1);
    renderReports();
  });
  content.querySelector("#reports-next")?.addEventListener("click", () => {
    state.reportList.page = Math.min(totalPages, state.reportList.page + 1);
    renderReports();
  });
}

function reportResultPill(result) {
  const value = String(result || "").trim() || "Draft";
  if (value === "Proceed to Next Step") return `<span class="pill green">${escapeHtml(value)}</span>`;
  if (value === "Watchlist") return `<span class="pill amber">${escapeHtml(value)}</span>`;
  if (value === "Archive") return `<span class="pill red">${escapeHtml(value)}</span>`;
  if (value.startsWith("Return to ")) return `<span class="pill cyan">${escapeHtml(value)}</span>`;
  return `<span class="pill">${escapeHtml(value)}</span>`;
}

function reportSummaryValue(report) {
  return String(report.summary || report.next_action || report.result || "").trim();
}

function reportSummaryCell(report) {
  const text = reportSummaryValue(report);
  const expandable = text.length > 140;
  return `
    <div class="summary-cell">
      <span class="summary-preview ${text ? "" : "muted"}">${escapeHtml(text || "No summary yet.")}</span>
      ${expandable ? `<button class="inline-expand-button" type="button" data-row-toggle="1" aria-expanded="false">...</button>` : ""}
    </div>
  `;
}

function reportCompletedCell(report) {
  const completed = report.completed_at ? formatDate(report.completed_at) : "";
  const updated = report.updated_at ? formatDate(report.updated_at) : "";
  if (completed) {
    return `
      <div class="report-meta-cell">
        <strong>${escapeHtml(completed)}</strong>
        ${updated && updated !== completed ? `<span class="muted">Updated ${escapeHtml(updated)}</span>` : ""}
      </div>
    `;
  }
  return `
    <div class="report-meta-cell">
      <strong>Draft</strong>
      ${updated ? `<span class="muted">Updated ${escapeHtml(updated)}</span>` : ""}
    </div>
  `;
}

function reportListTable(reports) {
  if (!reports.length) {
    return `<div class="empty-state">No reports match the current filters.</div>`;
  }
  return `
    <div class="table-wrap">
      <table class="report-list-table">
        <thead>
          <tr>
            <th>Completed</th>
            <th>Company</th>
            <th>Report</th>
            <th>Stage</th>
            <th>Result</th>
            <th>Summary</th>
          </tr>
        </thead>
        <tbody>
          ${reports.map((report) => `
            <tr class="clickable report-list-row" data-report-open="${report.id}" data-row-expanded="0">
              <td>${reportCompletedCell(report)}</td>
              <td>
                <div class="report-primary-cell">
                  <strong>${escapeHtml(report.ticker || "")}</strong>
                  <span class="muted">${escapeHtml(report.company_name || "")}</span>
                </div>
              </td>
              <td>
                <div class="report-primary-cell">
                  <strong>${escapeHtml(report.title || "")}</strong>
                  <span class="muted">${escapeHtml(report.report_month || "")}</span>
                </div>
              </td>
              <td><span class="table-cell-text">${escapeHtml(report.stage_name || "")}</span></td>
              <td>${reportResultPill(report.result)}</td>
              <td>${reportSummaryCell(report)}</td>
            </tr>
          `).join("")}
        </tbody>
      </table>
    </div>
  `;
}

function bindReportTable() {
  content.querySelectorAll("[data-report-open]").forEach((row) => {
    row.addEventListener("click", (event) => {
      if (event.target.closest("button, a, input, select, textarea, label")) return;
      openReport(Number(row.dataset.reportOpen));
    });
  });
}

async function renderFunnel() {
  const stageTabs = state.bootstrap.stages.map((stage) => `
    <button class="tab ${state.activeStageId === stage.id ? "active" : ""}" data-stage-tab="${stage.id}">
      ${escapeHtml(stage.name)}
    </button>
  `).join("");
  const stageQuery = state.activeStageId ? `&stage_id=${state.activeStageId}` : "";
  const data = await api(`/api/companies?bucket=funnel${stageQuery}`);
  content.innerHTML = `
    <section class="panel">
      <div class="panel-header">
        <div>
          <h3>Active Funnel</h3>
          <p class="muted">Companies move here once the first report starts.</p>
        </div>
        <button class="secondary" data-clear-stage>All Stages</button>
      </div>
      <div class="panel-body grid">
        <div class="tabs">${stageTabs}</div>
        ${companyTable(data.companies, "funnel")}
      </div>
    </section>
  `;
  content.querySelectorAll("[data-stage-tab]").forEach((button) => {
    button.addEventListener("click", () => {
      state.activeStageId = Number(button.dataset.stageTab);
      renderFunnel();
    });
  });
  content.querySelector("[data-clear-stage]").addEventListener("click", () => {
    state.activeStageId = null;
    renderFunnel();
  });
  bindCompanyTable();
  bindCompanyRowExpanders();
}

function companyTable(companies, bucket, options = {}) {
  if (!companies.length) {
    return `<div class="empty-state">No companies here yet.</div>`;
  }
  const isSummaryBucket = bucket === "watchlist" || bucket === "archive";
  const watchlist = bucket === "watchlist";
  const summaryHeading = options.summaryHeading || (isSummaryBucket ? "Visible Summary" : "Latest Report");
  return `
    <div class="table-wrap">
      <table class="company-list-table">
        <thead>
          <tr>
            <th>Ticker</th>
            <th>Company</th>
            <th>Status</th>
            <th>${escapeHtml(summaryHeading)}</th>
            <th>Next Action</th>
            <th>Review Date</th>
            ${watchlist ? "<th>Watch Rules</th>" : ""}
          </tr>
        </thead>
        <tbody>
          ${companies.map((company) => `
            <tr class="clickable company-list-row" data-company-id="${company.id}" data-row-expanded="0">
              <td><strong>${escapeHtml(company.ticker)}</strong></td>
              <td><span class="table-cell-text">${escapeHtml(company.name)}</span></td>
              <td>${statusPill(company)}</td>
              <td>${companySummaryCell(company, bucket)}</td>
              <td><span class="table-cell-text">${escapeHtml(company.next_action || "")}</span></td>
              <td><span class="table-cell-text">${escapeHtml(company.review_date || "")}</span></td>
              ${watchlist ? `<td>${watchlistRuleSummary(company.monitoring_rules || [])}</td>` : ""}
            </tr>
          `).join("")}
        </tbody>
      </table>
    </div>
  `;
}

function statusPill(company) {
  if (company.bucket === "funnel") {
    return `<span class="pill green">${escapeHtml(company.current_stage_name || "Funnel")}</span>`;
  }
  if (company.bucket === "watchlist") return `<span class="pill amber">Watchlist</span>`;
  if (company.bucket === "archive") return `<span class="pill red">Archive</span>`;
  if (company.bucket === "monitoring") return `<span class="pill cyan">Monitoring</span>`;
  return `<span class="pill">Pool</span>`;
}

function summaryText(company, bucket) {
  if (bucket === "watchlist") return escapeHtml(company.watchlist_conditions || company.latest_summary || "");
  if (bucket === "archive") return escapeHtml(company.archive_red_flags || company.latest_summary || "");
  return escapeHtml(company.latest_summary || company.latest_result || "");
}

function companySummaryValue(company, bucket) {
  if (bucket === "pool") {
    if (company.bucket === "watchlist") return company.watchlist_conditions || company.latest_summary || "";
    if (company.bucket === "archive") return company.archive_red_flags || company.latest_summary || "";
    return company.latest_summary || company.latest_result || "";
  }
  if (bucket === "watchlist") return company.watchlist_conditions || company.latest_summary || "";
  if (bucket === "archive") return company.archive_red_flags || company.latest_summary || "";
  return company.latest_summary || company.latest_result || "";
}

function companySummaryCell(company, bucket) {
  const text = String(companySummaryValue(company, bucket) || "").trim();
  const expandable = text.length > 120;
  return `
    <div class="summary-cell">
      <span class="summary-preview ${text ? "" : "muted"}">${escapeHtml(text || "No summary yet.")}</span>
      ${expandable ? `<button class="inline-expand-button" type="button" data-row-toggle="1" aria-expanded="false">...</button>` : ""}
    </div>
  `;
}

function watchlistRuleSummary(rules) {
  if (!rules.length) return `<span class="muted">No objective rules</span>`;
  return `
    <div class="rule-stack">
      ${rules.slice(0, 4).map((rule) => `
        <span class="pill ${rule.triggered ? "green" : "amber"}">
          ${escapeHtml(rule.metric_name)} ${escapeHtml(rule.comparator)} ${escapeHtml(rule.threshold_value ?? "")}
        </span>
      `).join("")}
      ${rules.length > 4 ? `<span class="muted">+${rules.length - 4} more</span>` : ""}
    </div>
  `;
}

function bindCompanyTable() {
  content.querySelectorAll("[data-company-id]").forEach((row) => {
    row.addEventListener("click", (event) => {
      if (event.target.closest("button, a, input, select, textarea, label")) return;
      openCompany(Number(row.dataset.companyId));
    });
  });
}

function bindCompanyRowExpanders() {
  content.querySelectorAll("[data-row-toggle]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      const row = button.closest("[data-row-expanded]");
      if (!row) return;
      const expanded = row.dataset.rowExpanded === "1";
      row.dataset.rowExpanded = expanded ? "0" : "1";
      button.setAttribute("aria-expanded", expanded ? "false" : "true");
      button.textContent = expanded ? "..." : "Hide";
    });
  });
}

async function openCompany(companyId) {
  const payload = await api(`/api/companies/${companyId}`);
  state.currentCompany = payload.company;
  titleEl.textContent = `${payload.company.ticker} Research`;
  eyebrowEl.textContent = "Company Page";
  status("");
  renderCompanyDetail(payload.company);
  queueDocumentStatusPolling("Company source");
}

function renderCompanyDetail(company) {
  const stageOptions = state.bootstrap.stages.map((stage) => {
    const selected = company.current_stage_id === stage.id ? "selected" : "";
    return `<option value="${stage.id}" ${selected}>${escapeHtml(stage.name)}</option>`;
  }).join("");
  content.innerHTML = `
    <section class="panel">
      <div class="panel-header detail-head">
        <div>
          <button class="secondary company-detail-back" data-back-view>Back</button>
          <h3 class="company-title">${escapeHtml(company.ticker)} - ${escapeHtml(company.name)}</h3>
          <p class="muted">${escapeHtml(company.notes || "No notes yet.")}</p>
        </div>
        <div class="button-row">
          ${statusPill(company)}
        </div>
      </div>
    </section>

    <section class="panel">
      <div class="panel-header">
        <div>
          <h3>Reports</h3>
          <p class="muted">Create or continue a stage report.</p>
        </div>
      </div>
      <div class="panel-body grid">
        <form class="report-quick-form" id="new-report-form">
          <label>
            <span>Stage</span>
            <select name="stage_id">${stageOptions}</select>
          </label>
          <label>
            <span>Report Month</span>
            <input name="report_month" placeholder="April 2026" />
          </label>
          <label class="report-quick-title">
            <span>Title</span>
            <input name="title" placeholder="Optional custom title" />
          </label>
          <div class="report-quick-action">
            <button class="primary">Create Report</button>
          </div>
        </form>
        ${reportList(company.reports || [])}
      </div>
    </section>

    <section class="panel">
      <div class="panel-header">
        <div>
          <h3>Company Sources</h3>
          <p class="muted">Collected across Data Collection and later reports. Use these in Screening and the underwriting stages.</p>
        </div>
        <div class="button-row">
          ${sourceVisualization(company.company_sources || [])}
          ${(company.company_sources || []).length ? detailToggleButton() : ""}
        </div>
      </div>
      <div class="panel-body grid">
        ${companySourceSummary(company.company_sources || [])}
        ${(company.company_sources || []).length ? `
          <div class="detail-region grid hidden" data-detail-region>
            ${sourceLibraryToolbar(company.company_sources || [])}
            ${companySourceList(company.company_sources || [])}
            <div class="empty-state hidden" data-library-empty="company-sources">No sources match the current filters.</div>
          </div>
        ` : ""}
      </div>
    </section>

    <section class="panel">
      <div class="panel-header">
        <div>
          <h3>Documents</h3>
          <p class="muted">Upload filings, presentations, notes, PDFs, spreadsheets, or any other file type. Common formats get an LLM-readable text view automatically.</p>
        </div>
        <div class="button-row">
          <button class="secondary" type="button" data-open-upload-dialog>Upload Document</button>
          ${(company.documents || []).length ? detailToggleButton() : ""}
        </div>
      </div>
      <div class="panel-body grid">
        ${documentSummary(company.documents || [])}
        ${(company.documents || []).length ? `
          <div class="detail-region grid hidden" data-detail-region>
            ${documentLibraryToolbar(company.documents || [])}
            ${documentList(company.documents || [])}
            <div class="empty-state hidden" data-library-empty="company-documents">No documents match the current filters.</div>
          </div>
        ` : ""}
      </div>
    </section>

    <section class="panel">
      <div class="panel-header">
        <div>
          <h3>Monitoring Rules</h3>
          <p class="muted">Rules are triggered when the current value meets the threshold.</p>
        </div>
      </div>
      <div class="panel-body">
        ${monitoringRuleList(company.monitoring_rules)}
      </div>
    </section>
    ${documentUploadDialogMarkup(company)}
    ${documentPreviewDialogMarkup()}
  `;
  content.querySelector("[data-back-view]").addEventListener("click", () => renderView(state.view));
  content.querySelector("#new-report-form").addEventListener("submit", createReportForCompany);
  content.querySelector("#upload-form").addEventListener("submit", uploadDocument);
  content.querySelectorAll(".existing-rule").forEach((form) => {
    form.addEventListener("submit", updateMonitoringRule);
  });
  content.querySelectorAll("[data-report-id]").forEach((button) => {
    button.addEventListener("click", () => openReport(Number(button.dataset.reportId)));
  });
  bindCompanyUploadDialog();
  content.querySelectorAll("[data-delete-company-source]").forEach((button) => {
    button.addEventListener("click", async () => {
      const sourceId = Number(button.dataset.deleteCompanySource);
      if (!sourceId) return;
      const sourceTitle = button.dataset.sourceTitle || "this source";
      if (!window.confirm(`Delete ${sourceTitle}? This removes it from the company source library and unlinks cited answers that reference it.`)) return;
      await deleteCompanySource(sourceId, company.id);
    });
  });
  bindCompanyLibraryControls();
  bindDetailToggleButtons();
  bindDeleteReportButtons();
  bindPreviewButtons();
}

function reportFreshnessValue(report) {
  const timestamp = Date.parse(report?.updated_at || report?.created_at || "");
  return Number.isFinite(timestamp) ? timestamp : 0;
}

function latestReportsByStage(reports) {
  const sorted = [...(reports || [])].sort((left, right) => reportFreshnessValue(right) - reportFreshnessValue(left) || Number(right.id) - Number(left.id));
  const latest = new Map();
  const older = [];
  sorted.forEach((report) => {
    const key = String(report.stage_id || report.stage_key || report.stage_name || report.id);
    if (!latest.has(key)) {
      latest.set(key, report);
      return;
    }
    older.push(report);
  });
  return {
    latestReports: [...latest.values()].sort(
      (left, right) => Number(right.stage_sequence || 0) - Number(left.stage_sequence || 0) || reportFreshnessValue(right) - reportFreshnessValue(left),
    ),
    olderReports: older.sort(
      (left, right) => Number(right.stage_sequence || 0) - Number(left.stage_sequence || 0) || reportFreshnessValue(right) - reportFreshnessValue(left) || Number(right.id) - Number(left.id),
    ),
  };
}

function staleReportIds(reports) {
  const ids = new Set();
  (reports || []).forEach((report) => {
    const newerEarlierStageExists = (reports || []).some((candidate) => {
      if (Number(candidate.id) === Number(report.id)) return false;
      return Number(candidate.stage_sequence || 0) < Number(report.stage_sequence || 0)
        && reportFreshnessValue(candidate) > reportFreshnessValue(report);
    });
    if (newerEarlierStageExists) ids.add(Number(report.id));
  });
  return ids;
}

function reportTable(reports, staleIds, emptyMessage = "No reports yet.") {
  if (!reports.length) return `<div class="empty-state">${escapeHtml(emptyMessage)}</div>`;
  return `
    <div class="table-wrap">
      <table>
        <thead><tr><th>Report</th><th>Stage</th><th>Result</th><th>Updated</th><th></th></tr></thead>
        <tbody>
          ${reports.map((report) => `
            <tr class="${staleIds.has(Number(report.id)) ? "report-row-stale" : ""}">
              <td>
                <strong>${escapeHtml(report.title)}</strong>
                ${staleIds.has(Number(report.id)) ? `<br><span class="muted">Earlier-stage work is newer.</span>` : ""}
              </td>
              <td>${escapeHtml(report.stage_name)}</td>
              <td>${escapeHtml(report.result)}</td>
              <td>${formatDate(report.updated_at)}</td>
              <td>
                <div class="button-row">
                  <button class="small-button" data-report-id="${report.id}">Open</button>
                  <button class="small-button danger" type="button" data-delete-report="${report.id}" data-company-id="${report.company_id || state.currentCompany?.id || ""}" data-report-title="${escapeAttr(report.title)}">Delete</button>
                </div>
              </td>
            </tr>
          `).join("")}
        </tbody>
      </table>
    </div>
  `;
}

function reportList(reports) {
  if (!reports.length) return `<div class="empty-state">No reports yet.</div>`;
  const grouped = latestReportsByStage(reports);
  const staleIds = staleReportIds(reports);
  const showLegend = staleIds.size > 0;
  return `
    ${showLegend ? `<div class="report-legend"><span class="pill report-warning-pill">Rows in yellow may need updating because an earlier-stage report was revised more recently.</span></div>` : ""}
    <div class="report-stack">
      <div class="report-stack-section">
        <div class="section-heading">
          <div>
            <h4>Latest By Stage</h4>
            <p class="muted">The newest report for each stage stays visible by default.</p>
          </div>
        </div>
        ${reportTable(grouped.latestReports, staleIds)}
      </div>
      ${grouped.olderReports.length ? `
        <div class="report-stack-section">
          <div class="section-heading">
            <div>
              <h4>Older Reports</h4>
              <p class="muted">${grouped.olderReports.length} previous report${grouped.olderReports.length === 1 ? "" : "s"} hidden by default.</p>
            </div>
            ${detailToggleButton({ expandLabel: "Show Older Reports", collapseLabel: "Hide Older Reports" })}
          </div>
          <div class="detail-region grid hidden" data-detail-region>
            ${reportTable(grouped.olderReports, staleIds, "No older reports.")}
          </div>
        </div>
      ` : ""}
    </div>
  `;
}

function detailToggleButton({ expanded = false, expandLabel = "More Detail", collapseLabel = "Less Detail" } = {}) {
  return `
    <button
      class="secondary detail-toggle-button"
      type="button"
      data-detail-toggle="1"
      data-expand-label="${escapeAttr(expandLabel)}"
      data-collapse-label="${escapeAttr(collapseLabel)}"
      aria-expanded="${expanded ? "true" : "false"}"
    >${expanded ? collapseLabel : expandLabel}</button>
  `;
}

function countByLabel(items, getLabel) {
  return (items || []).reduce((acc, item) => {
    const label = String(getLabel(item) || "").trim() || "Unspecified";
    acc[label] = (acc[label] || 0) + 1;
    return acc;
  }, {});
}

function sortedCountEntries(counts) {
  return Object.entries(counts || {}).sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]));
}

function summaryMetric(label, value, helper = "") {
  return `
    <div class="summary-metric-card">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(String(value))}</strong>
      ${helper ? `<small>${escapeHtml(helper)}</small>` : ""}
    </div>
  `;
}

function breakdownPills(title, counts, toneForLabel = null) {
  const entries = sortedCountEntries(counts);
  if (!entries.length) return "";
  return `
    <div class="summary-breakdown">
      <span>${escapeHtml(title)}</span>
      <div class="tag-row">
        ${entries.map(([label, count]) => {
          const tone = toneForLabel ? toneForLabel(label) : "";
          const className = tone ? `pill ${tone}` : "pill";
          return `<span class="${className}">${escapeHtml(label)} ${escapeHtml(String(count))}</span>`;
        }).join("")}
      </div>
    </div>
  `;
}

function sourceStatusLabelTone(label) {
  if (label === "Ready") return "green";
  if (label === "Limited" || label === "Link Only") return "amber";
  if (label === "Failed") return "red";
  return "";
}

function companySourceSummary(sources) {
  if (!sources.length) {
    return `<div class="empty-state">No company sources yet. Start with a Data Collection report and import the source pack there.</div>`;
  }
  const total = sources.length;
  const ready = sources.filter((source) => sourceReusabilityStatus(source) === "ready").length;
  const withArtifacts = sources.filter((source) => source.document_id).length;
  const liveLinks = sources.filter((source) => source.url).length;
  const byType = countByLabel(sources, (source) => source.source_type || "Unspecified type");
  const byStatus = countByLabel(sources, (source) => sourceReusabilityLabel(source));
  return `
    <div class="summary-metric-grid">
      ${summaryMetric("Total Sources", total, "Company-wide library")}
      ${summaryMetric("LLM Ready", ready, "Immediately reusable")}
      ${summaryMetric("Stored Artifacts", withArtifacts, "Captured files or snapshots")}
      ${summaryMetric("Live Links", liveLinks, "External references")}
    </div>
    ${breakdownPills("Source Types", byType)}
    ${breakdownPills("Reuse Status", byStatus, sourceStatusLabelTone)}
  `;
}

function documentStatusLabel(document) {
  if (document.normalized_status === "pending") return "Pending";
  if (document.normalized_status === "ready") return "Ready";
  if (document.normalized_status === "limited") return "Limited";
  if (document.normalized_status === "failed") return "Failed";
  return "Pending";
}

function documentStatusLabelTone(label) {
  if (label === "Ready") return "green";
  if (label === "Limited") return "amber";
  if (label === "Failed") return "red";
  return "";
}

function documentCategory(document) {
  const mime = String(document.mime_type || "").toLowerCase();
  const name = String(document.original_name || "").toLowerCase();
  if (mime.includes("pdf") || name.endsWith(".pdf")) return "PDF";
  if (mime.includes("html") || name.endsWith(".html") || name.endsWith(".htm")) return "HTML";
  if (mime.includes("csv") || name.endsWith(".csv")) return "CSV";
  if (mime.includes("sheet") || mime.includes("excel") || name.endsWith(".xlsx") || name.endsWith(".xls")) return "Spreadsheet";
  if (mime.includes("json") || name.endsWith(".json")) return "JSON";
  if (mime.includes("markdown") || name.endsWith(".md")) return "Markdown";
  if (mime.includes("word") || name.endsWith(".doc") || name.endsWith(".docx")) return "Word";
  if (mime.includes("presentation") || name.endsWith(".ppt") || name.endsWith(".pptx")) return "Presentation";
  if (mime.startsWith("text/") || name.endsWith(".txt")) return "Text";
  return "Other";
}

function documentSummary(documents) {
  if (!documents.length) {
    return `<div class="empty-state">No documents uploaded.</div>`;
  }
  const total = documents.length;
  const ready = documents.filter((document) => document.normalized_status === "ready").length;
  const companyLevel = documents.filter((document) => !document.report_id).length;
  const reportLinked = documents.filter((document) => document.report_id).length;
  const byType = countByLabel(documents, documentCategory);
  const byStatus = countByLabel(documents, documentStatusLabel);
  return `
    <div class="summary-metric-grid">
      ${summaryMetric("Total Documents", total, "Uploaded to the company")}
      ${summaryMetric("LLM Ready", ready, "Normalized and searchable")}
      ${summaryMetric("Company Level", companyLevel, "Not tied to a report")}
      ${summaryMetric("Report Linked", reportLinked, "Attached to reports")}
    </div>
    ${breakdownPills("Formats", byType)}
    ${breakdownPills("Normalization Status", byStatus, documentStatusLabelTone)}
  `;
}

function sourceLibraryToolbar(sources) {
  const typeOptions = sortedCountEntries(countByLabel(sources, (source) => source.source_type || "Unspecified type"))
    .map(([label]) => `<option value="${escapeAttr(label)}">${escapeHtml(label)}</option>`)
    .join("");
  return `
    <div class="library-toolbar" data-library-toolbar="company-sources">
      <label class="toolbar-search">Search
        <input data-library-search placeholder="Search title, citation, or stage" />
      </label>
      <label>Type
        <select data-library-type>
          <option value="">All types</option>
          ${typeOptions}
        </select>
      </label>
      <label>Reuse
        <select data-library-status>
          <option value="">All reuse states</option>
          <option value="Ready">Ready</option>
          <option value="Limited">Limited</option>
          <option value="Pending">Pending</option>
          <option value="Link Only">Link Only</option>
          <option value="Failed">Failed</option>
        </select>
      </label>
      <label>Sort
        <select data-library-sort>
          <option value="newest">Newest</option>
          <option value="oldest">Oldest</option>
          <option value="title_asc">Title A-Z</option>
          <option value="stage_asc">Stage</option>
        </select>
      </label>
    </div>
  `;
}

function documentLibraryToolbar(documents) {
  const formatOptions = sortedCountEntries(countByLabel(documents, documentCategory))
    .map(([label]) => `<option value="${escapeAttr(label)}">${escapeHtml(label)}</option>`)
    .join("");
  return `
    <div class="library-toolbar" data-library-toolbar="company-documents">
      <label class="toolbar-search">Search
        <input data-library-search placeholder="Search file name or notes" />
      </label>
      <label>Format
        <select data-library-type>
          <option value="">All formats</option>
          ${formatOptions}
        </select>
      </label>
      <label>Status
        <select data-library-status>
          <option value="">All statuses</option>
          <option value="Ready">Ready</option>
          <option value="Limited">Limited</option>
          <option value="Pending">Pending</option>
          <option value="Failed">Failed</option>
        </select>
      </label>
      <label>Sort
        <select data-library-sort>
          <option value="newest">Newest</option>
          <option value="oldest">Oldest</option>
          <option value="name_asc">Name A-Z</option>
          <option value="size_desc">Largest first</option>
        </select>
      </label>
    </div>
  `;
}

function documentList(documents) {
  if (!documents.length) return `<div class="empty-state">No documents uploaded.</div>`;
  return `
    <div class="table-wrap" data-library-table="company-documents">
      <table>
        <thead><tr><th>File</th><th>Type</th><th>LLM View</th><th>Size</th><th>Notes</th><th></th></tr></thead>
        <tbody>
          ${documents.map((doc) => `
            <tr
              data-library-row
              data-search-text="${escapeAttr([doc.original_name, doc.notes, doc.mime_type].filter(Boolean).join(" ").toLowerCase())}"
              data-library-type="${escapeAttr(documentCategory(doc))}"
              data-library-status="${escapeAttr(documentStatusLabel(doc))}"
              data-sort-name="${escapeAttr((doc.original_name || "").toLowerCase())}"
              data-sort-size="${escapeAttr(String(doc.size_bytes || 0))}"
              data-sort-date="${escapeAttr(String(Date.parse(doc.uploaded_at || "") || 0))}"
            >
              <td>${escapeHtml(doc.original_name)}</td>
              <td>${escapeHtml(doc.mime_type)}</td>
              <td>${llmDocumentBadge(doc)}${doc.normalized_preview ? `<br><button type="button" class="small-button" data-preview-document="${doc.id}">Preview</button>` : ""}</td>
              <td>${formatBytes(doc.size_bytes)}</td>
              <td>${escapeHtml(doc.notes || "")}</td>
              <td>
                <div class="button-row">
                  ${doc.normalized_available ? `<a class="small-button" href="/api/documents/${doc.id}/normalized" target="_blank" rel="noreferrer">LLM</a>` : ""}
                  <a class="small-button" href="/api/documents/${doc.id}/download">Download</a>
                </div>
              </td>
            </tr>
          `).join("")}
        </tbody>
      </table>
    </div>
  `;
}

function companySourceList(sources) {
  if (!sources.length) return `<div class="empty-state">No company sources yet. Start with a Data Collection report and import the source pack there.</div>`;
  return `
    <div class="table-wrap" data-library-table="company-sources">
      <table class="source-table">
        <thead><tr><th>Source</th><th>Stage</th><th>Type</th><th>Reuse</th><th>Preview</th><th>Actions</th></tr></thead>
        <tbody>
          ${sources.map((source) => `
            <tr
              data-library-row
              data-search-text="${escapeAttr([source.title, source.citation, source.stage_name, source.report_title, source.source_type].filter(Boolean).join(" ").toLowerCase())}"
              data-library-type="${escapeAttr(source.source_type || "Unspecified type")}"
              data-library-status="${escapeAttr(sourceReusabilityLabel(source))}"
              data-sort-title="${escapeAttr((source.title || "").toLowerCase())}"
              data-sort-stage="${escapeAttr(`${String(source.stage_sequence || 999).padStart(4, "0")}-${(source.stage_name || "").toLowerCase()}`)}"
              data-sort-date="${escapeAttr(String(Date.parse(source.updated_at || source.created_at || "") || 0))}"
            >
              <td><strong>${escapeHtml(source.title)}</strong>${source.citation ? `<br><span class="muted">${escapeHtml(source.citation)}</span>` : ""}</td>
              <td>${escapeHtml(source.stage_name || "")}${source.report_title ? `<br><span class="muted">${escapeHtml(source.report_title)}</span>` : ""}</td>
              <td>${escapeHtml(source.source_type || "")}</td>
              <td>${llmSourceBadge(source)}${sourceCapabilityRow(source)}</td>
              <td>${source.normalized_preview ? `<button type="button" class="small-button" data-preview-document="${source.document_id}">Preview</button>` : `<span class="muted">No preview</span>`}</td>
              <td>
                <div class="button-row">
                  ${source.document_id && source.normalized_available ? `<a class="small-button" href="/api/documents/${source.document_id}/normalized" target="_blank" rel="noreferrer">LLM</a>` : ""}
                  ${source.document_id ? `<a class="small-button" href="/api/documents/${source.document_id}/download">File</a>` : ""}
                  ${source.url ? `<a class="small-button" href="${escapeAttr(source.url)}" target="_blank" rel="noreferrer">Link</a>` : ""}
                  <button type="button" class="small-button danger" data-delete-company-source="${source.id}" data-source-title="${escapeAttr(source.title)}">Delete</button>
                </div>
              </td>
            </tr>
          `).join("")}
        </tbody>
      </table>
    </div>
  `;
}

function bindCompanyLibraryControls() {
  bindLibraryToolbar("company-sources", {
    sorters: {
      newest: (left, right) => Number(right.dataset.sortDate || 0) - Number(left.dataset.sortDate || 0),
      oldest: (left, right) => Number(left.dataset.sortDate || 0) - Number(right.dataset.sortDate || 0),
      title_asc: (left, right) => String(left.dataset.sortTitle || "").localeCompare(String(right.dataset.sortTitle || "")),
      stage_asc: (left, right) => String(left.dataset.sortStage || "").localeCompare(String(right.dataset.sortStage || "")),
    },
  });
  bindLibraryToolbar("company-documents", {
    sorters: {
      newest: (left, right) => Number(right.dataset.sortDate || 0) - Number(left.dataset.sortDate || 0),
      oldest: (left, right) => Number(left.dataset.sortDate || 0) - Number(right.dataset.sortDate || 0),
      name_asc: (left, right) => String(left.dataset.sortName || "").localeCompare(String(right.dataset.sortName || "")),
      size_desc: (left, right) => Number(right.dataset.sortSize || 0) - Number(left.dataset.sortSize || 0),
    },
  });
}

function bindLibraryToolbar(name, options = {}) {
  const toolbar = content.querySelector(`[data-library-toolbar="${name}"]`);
  const tableWrap = content.querySelector(`[data-library-table="${name}"]`);
  const emptyState = content.querySelector(`[data-library-empty="${name}"]`);
  if (!toolbar || !tableWrap) return;
  const tbody = tableWrap.querySelector("tbody");
  const rows = [...tbody.querySelectorAll("[data-library-row]")];
  const apply = () => {
    const search = String(toolbar.querySelector("[data-library-search]")?.value || "").trim().toLowerCase();
    const type = String(toolbar.querySelector("[data-library-type]")?.value || "");
    const status = String(toolbar.querySelector("[data-library-status]")?.value || "");
    const sort = String(toolbar.querySelector("[data-library-sort]")?.value || "newest");
    const sorter = options.sorters?.[sort];
    const ordered = sorter ? [...rows].sort(sorter) : rows;
    let visibleCount = 0;
    ordered.forEach((row) => {
      const matchesSearch = !search || String(row.dataset.searchText || "").includes(search);
      const matchesType = !type || String(row.dataset.libraryType || "") === type;
      const matchesStatus = !status || String(row.dataset.libraryStatus || "") === status;
      const visible = matchesSearch && matchesType && matchesStatus;
      row.classList.toggle("hidden", !visible);
      if (visible) visibleCount += 1;
      tbody.appendChild(row);
    });
    emptyState?.classList.toggle("hidden", visibleCount !== 0);
  };
  toolbar.querySelectorAll("input, select").forEach((field) => {
    field.addEventListener(field.tagName === "INPUT" ? "input" : "change", apply);
  });
  apply();
}

function monitoringRuleList(rules) {
  if (!rules.length) return `<div class="empty-state">No monitoring rules yet.</div>`;
  return `
    <div class="grid">
      ${rules.map((rule) => `
        <form class="objective-rule existing-rule" data-rule-id="${rule.id}">
          <label>Metric <input value="${escapeAttr(rule.metric_name)}" disabled /></label>
          <label>Check <input value="${escapeAttr(rule.comparator)}" disabled /></label>
          <label>Threshold <input value="${escapeAttr(`${rule.threshold_value ?? ""} ${rule.unit || ""}`.trim())}" disabled /></label>
          <label>Current <input name="current_value" type="number" step="any" value="${escapeAttr(rule.current_value ?? "")}" /></label>
          <label class="full">Notes <textarea name="notes" rows="2">${escapeHtml(rule.notes || "")}</textarea></label>
          <div>
            <span class="pill ${rule.triggered ? "green" : ""}">${rule.triggered ? "Triggered" : "Waiting"}</span>
            <button class="small-button">Save</button>
          </div>
        </form>
      `).join("")}
    </div>
  `;
}

function llmDocumentBadge(doc) {
  if (!doc.normalized_status || doc.normalized_status === "pending") return `<span class="pill amber">Pending</span>`;
  const tone = doc.normalized_status === "ready" ? "green" : doc.normalized_status === "limited" ? "amber" : "red";
  const label = doc.normalized_format || documentStatusLabel(doc);
  return `<span class="pill ${tone}">${escapeHtml(label)}</span>`;
}

function sourceStatusTone(status) {
  if (status === "ready") return "green";
  if (status === "limited" || status === "link_only" || status === "pending") return "amber";
  if (status === "failed") return "red";
  return "";
}

function sourceReusabilityStatus(source) {
  return source.capture_state || source.reusability_status || (source.document_id ? (source.normalized_status || "pending") : "link_only");
}

function sourceReusabilityLabel(source) {
  const labels = {
    ready: "Ready",
    limited: "Limited",
    pending: "Pending",
    link_only: "Link Only",
    failed: "Failed",
  };
  return labels[sourceReusabilityStatus(source)] || "Pending";
}

function llmSourceBadge(source) {
  const status = sourceReusabilityStatus(source);
  return `<span class="pill ${sourceStatusTone(status)}">${escapeHtml(sourceReusabilityLabel(source))}</span>`;
}

function sourceCapabilityRow(source) {
  const pills = [];
  if (source.url) pills.push(`<span class="pill">Live link</span>`);
  if (source.document_id) pills.push(`<span class="pill">${escapeHtml(source.capture_kind === "inline_snapshot" ? "Inline snapshot" : "Stored artifact")}</span>`);
  if (source.capture_state === "pending") pills.push(`<span class="pill amber">Processing</span>`);
  if (source.document_id && source.normalized_available) pills.push(`<span class="pill green">LLM view</span>`);
  if (source.document_id && !source.normalized_available && source.capture_state !== "pending") pills.push(`<span class="pill amber">No LLM view</span>`);
  const summary = pills.length ? `<div class="tag-row">${pills.join("")}</div>` : "";
  const reasonText = source.reusability_reason || sourceReasonForState(source);
  const reason = reasonText ? `<div class="muted">${escapeHtml(reasonText)}</div>` : "";
  const linkOnly = source.capture_state === "link_only"
    ? `
      ${source.link_only_reason ? `<div class="muted"><strong>Why link-only:</strong> ${escapeHtml(source.link_only_reason)}</div>` : ""}
      <div class="muted">Next step: upload an HTML, Markdown/text, CSV, or spreadsheet snapshot in this source.</div>
    `
    : "";
  return `${summary}${reason}${linkOnly}`;
}

function sourceStageContext(source) {
  return [source.stage_name, source.report_title].filter(Boolean).join(" · ");
}

function sourceOpenLinks(source) {
  const links = [];
  if (source.url) links.push(`<a href="${escapeAttr(source.url)}" target="_blank" rel="noreferrer">Link</a>`);
  if (source.document_id && source.normalized_available) links.push(`<a href="/api/documents/${source.document_id}/normalized" target="_blank" rel="noreferrer">LLM</a>`);
  if (source.document_id) links.push(`<a href="/api/documents/${source.document_id}/download">File</a>`);
  return links.join("<br>");
}

function uniqueSourcesById(sources) {
  const seen = new Set();
  return (sources || []).filter((source) => {
    const key = String(source.id || "");
    if (!key || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function editableReportSources(report) {
  return uniqueSourcesById(report?.sources || []);
}

function reportSourceGroups(report) {
  const reportSources = editableReportSources(report);
  const reportIds = new Set(reportSources.map((source) => String(source.id)));
  const suggestedSources = uniqueSourcesById((report?.suggested_sources || []).filter((source) => !reportIds.has(String(source.id))));
  const suggestedIds = new Set(suggestedSources.map((source) => String(source.id)));
  const companyLibrary = uniqueSourcesById(report?.company_sources?.length ? report.company_sources : [...reportSources, ...suggestedSources]);
  const remainingCompanySources = companyLibrary.filter((source) => !reportIds.has(String(source.id)) && !suggestedIds.has(String(source.id)));
  return {
    reportSources,
    suggestedSources,
    remainingCompanySources,
    allAvailableSources: uniqueSourcesById([...reportSources, ...suggestedSources, ...remainingCompanySources]),
  };
}

function sourceGroupSection(title, description, sources, options = {}) {
  return `
    <div class="source-group">
      <div class="detail-head">
        <div>
          <h4>${escapeHtml(title)}</h4>
          ${description ? `<p class="muted">${escapeHtml(description)}</p>` : ""}
        </div>
        ${sourceVisualization(sources)}
      </div>
      ${sourceRows(sources, options)}
    </div>
  `;
}

async function openReport(reportId) {
  const payload = await api(`/api/reports/${reportId}`);
  state.completionPreview = null;
  state.currentReport = payload.report;
  titleEl.textContent = payload.report.title;
  eyebrowEl.textContent = `${payload.report.ticker} - ${payload.report.stage_name}`;
  renderReportEditor(payload.report);
  queueDocumentStatusPolling("Source");
}

function savedReportCompletionState(report) {
  return report?.completion || report?.agent_contract?.completion || {};
}

function activeCompletionState(report) {
  if (state.completionPreview && Number(state.completionPreview.reportId) === Number(report?.id)) {
    return {
      completion: state.completionPreview.completion || {},
      isPreview: true,
    };
  }
  return {
    completion: savedReportCompletionState(report),
    isPreview: false,
  };
}

function completionStatusTone(status) {
  if (status === "complete") return "green";
  if (status === "ready_to_finalize") return "cyan";
  if (status === "in_progress" || status === "incomplete") return "amber";
  return "";
}

function formatCompletionPct(value) {
  const numeric = Number(value || 0);
  return Number.isFinite(numeric) ? `${numeric.toFixed(numeric % 1 === 0 ? 0 : 1)}%` : "0%";
}

function blockerSummaryPills(completion) {
  return [
    [`Covered ${completion.covered_field_count || 0}/${completion.field_count || 0}`, "cyan"],
    [`Sourced ${completion.sourced_field_count || 0}/${completion.source_required_field_count || 0}`, "green"],
    [`Required Notes ${completion.required_noted_field_count || 0}/${completion.required_note_field_count || 0}`, (completion.missing_required_note_ids || []).length ? "amber" : ""],
    [`Exempt ${completion.exempt_field_count || 0}`, ""],
    [`Template ${completion.template_field_count || completion.field_count || 0}`, ""],
  ];
}

function completionList(items, prefix = "") {
  return `<ul>${items.map((field) => `<li>${prefix}${escapeHtml(field.section_title)}: ${escapeHtml(field.label)}</li>`).join("")}</ul>`;
}

function reportQualityPanel(report) {
  const { completion, isPreview } = activeCompletionState(report);
  if (!completion || !Object.keys(completion).length) return "";
  const blockers = [];
  if ((completion.missing_fields || []).length) blockers.push(completionList(completion.missing_fields));
  if ((completion.missing_source_links || []).length) {
    blockers.push(completionList(completion.missing_source_links, "Missing source: "));
  }
  if ((completion.blocked_source_links || []).length) {
    blockers.push(completionList(completion.blocked_source_links, "Blocked source: "));
  }
  if ((completion.missing_required_notes || []).length) {
    blockers.push(completionList(completion.missing_required_notes, "Missing required note: "));
  }
  if ((completion.exception_missing_notes || []).length) {
    blockers.push(completionList(completion.exception_missing_notes, "Exception needs note: "));
  }
  if ((completion.decision_requirements || []).length) {
    blockers.push(`<ul>${completion.decision_requirements.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`);
  }
  const warnings = completion.warnings || [];
  const incompleteSections = (completion.section_progress || []).filter(
    (section) => Number(section.field_count || 0) > 0 && Number(section.covered_field_count || 0) < Number(section.field_count || 0)
  );
  return `
    <section class="panel">
      <div class="panel-header">
        <div>
          <h3>Completion Quality</h3>
          <p class="muted">The full template always stays visible. Finalize only persists the non-draft report result after every non-exempt field is covered, sourced, and note-complete where required.${isPreview ? " Showing an unsaved preview of the current form state." : " Showing the last saved report state until you refresh the preview."}</p>
        </div>
        <div class="button-row">
          ${isPreview ? `<span class="pill cyan">Unsaved preview</span>` : ""}
          <span class="pill ${completionStatusTone(completion.status)}">${escapeHtml(completion.status || "unknown")}</span>
          <button type="button" class="secondary" data-refresh-completion-preview="1">Refresh completion preview</button>
        </div>
      </div>
      <div class="panel-body grid report-quality-panel">
        <div class="rule-stack">
          ${blockerSummaryPills(completion).map(([label, tone]) => `<span class="pill ${tone}">${escapeHtml(label)}</span>`).join("")}
          <span class="pill">Coverage ${escapeHtml(formatCompletionPct(completion.coverage_pct))}</span>
          <span class="pill">Source Coverage ${escapeHtml(formatCompletionPct(completion.source_coverage_pct))}</span>
          <span class="pill">Notes Coverage ${escapeHtml(formatCompletionPct(completion.notes_coverage_pct))}</span>
          ${completion.final_decision ? `<span class="pill">${escapeHtml(completion.final_decision)}</span>` : `<span class="pill amber">No final decision</span>`}
          ${completion.legacy_incomplete_finalized ? `<span class="pill amber">Saved report fails current standard</span>` : ""}
        </div>
        ${blockers.length ? `<div class="source-guidance-box warning-box"><strong>Blocking Gaps</strong>${blockers.join("")}</div>` : ""}
        ${warnings.length ? `<div class="source-guidance-box warning-box"><strong>Warnings</strong><div class="muted">${warnings.map((warning) => escapeHtml(warning)).join("<br>")}</div></div>` : ""}
        ${incompleteSections.length ? `
          <div class="source-guidance-box">
            <strong>Section Progress</strong>
            <div class="tag-row">
              ${incompleteSections.map((section) => `
                <span class="pill amber">${escapeHtml(section.title)} ${escapeHtml(String(section.covered_field_count || 0))}/${escapeHtml(String(section.field_count || 0))}</span>
              `).join("")}
            </div>
          </div>
        ` : ""}
      </div>
    </section>
  `;
}

function reportQualityBanner(report) {
  return `<div id="report-quality-slot">${reportQualityPanel(report)}</div>`;
}

function renderReportQualityPanel() {
  const slot = content.querySelector("#report-quality-slot");
  if (!slot || !state.currentReport) return;
  slot.innerHTML = reportQualityPanel(state.currentReport);
  bindCompletionPreviewButton();
}

function fieldContextPresent(key) {
  const sourceEntry = state.fieldSources?.[key] || {};
  return Boolean(
    (sourceEntry.source_ids || []).length
    || String(sourceEntry.citation || "").trim()
    || String(state.fieldNotes?.[key] || "").trim()
    || String(state.fieldExceptions?.[key] || "").trim()
  );
}

function fieldHasDisplayContent(field, report) {
  if (!field) return false;
  const value = fieldValue(field, report);
  if (field.kind === "checkbox") {
    if (value === true || value === "true") return true;
  } else if (String(value ?? "").trim()) {
    return true;
  }
  return fieldContextPresent(field.id);
}

function reportFieldWrapperAttrs(field, report) {
  return `data-report-field-for="${escapeAttr(field.id)}" data-field-filled="${fieldHasDisplayContent(field, report) ? "1" : "0"}"`;
}

function reportRowAttrs(fields, report) {
  const filled = (fields || []).some((field) => field && fieldHasDisplayContent(field, report));
  return `data-report-row="1" data-row-filled="${filled ? "1" : "0"}"`;
}

function sectionHasDisplayContext(sectionId) {
  return fieldContextPresent(`section:${sectionId}`);
}

function currentFieldHasInputValue(fieldId) {
  const inputs = [...content.querySelectorAll(`[data-field-id="${CSS.escape(fieldId)}"]`)];
  if (!inputs.length) return false;
  if (inputs.some((input) => input.type === "radio")) {
    return inputs.some((input) => input.checked);
  }
  if (inputs.some((input) => input.type === "checkbox")) {
    return inputs.some((input) => input.checked);
  }
  return inputs.some((input) => String(input.value || "").trim());
}

function refreshReportVisibilityContainers() {
  content.querySelectorAll("[data-report-row]").forEach((row) => {
    const hasFilledField = Boolean(row.querySelector('[data-report-field-for][data-field-filled="1"]'));
    row.dataset.rowFilled = hasFilledField ? "1" : "0";
  });
  content.querySelectorAll(".report-section[data-section-id]").forEach((section) => {
    const sectionId = section.dataset.sectionId;
    const hasSectionContext = sectionHasDisplayContext(sectionId);
    const hasFilledField = Boolean(
      section.querySelector('[data-report-field-for][data-field-filled="1"], [data-report-row][data-row-filled="1"], .bold-result input:checked')
    );
    section.dataset.sectionFilled = hasSectionContext || hasFilledField ? "1" : "0";
  });
  refreshAnswerableSectionSummaries();
}

function updateReportVisibilityUI() {
  refreshReportVisibilityContainers();
}

function syncRenderedFieldState(fieldId) {
  const filled = currentFieldHasInputValue(fieldId) || fieldContextPresent(fieldId);
  content.querySelectorAll(`[data-report-field-for="${CSS.escape(fieldId)}"]`).forEach((node) => {
    node.dataset.fieldFilled = filled ? "1" : "0";
  });
  refreshReportVisibilityContainers();
}

function renderReportEditor(report) {
  state.fieldSources = report.field_sources || {};
  state.fieldNotes = report.field_notes || {};
  state.fieldExceptions = report.field_exceptions || {};
  if (isDataCollectionReport(report)) {
    renderDataCollectionReportEditor(report);
    return;
  }
  if (isScreeningReport(report)) {
    renderScreeningReportEditor(report);
    return;
  }
  if (isBusinessUnderwritingReport(report)) {
    renderBusinessUnderwritingReportEditor(report);
    return;
  }
  if (isManagementUnderwritingReport(report)) {
    renderManagementUnderwritingReportEditor(report);
    return;
  }
  if (isFinancialUnderwritingReport(report)) {
    renderFinancialUnderwritingReportEditor(report);
    return;
  }
  if (isValuationPositionSizeReport(report)) {
    renderValuationPositionSizeReportEditor(report);
    return;
  }
  if (isExecutionRulesReport(report)) {
    renderExecutionRulesReportEditor(report);
    return;
  }
  const template = report.template;
  const schema = template.schema || { sections: [] };
  content.innerHTML = `
    <form id="report-form" class="grid">
      <section class="panel">
        <div class="panel-header detail-head">
          <div>
            <button class="secondary" type="button" data-company-return="${report.company_id}">Back to Company</button>
            <p class="eyebrow">${escapeHtml(report.stage_name)}</p>
            <h3 class="company-title">${escapeHtml(report.title)}</h3>
            <p class="muted">${escapeHtml(template.name)} - ${schema.field_count || 0} fields from this pinned template snapshot.</p>
          </div>
          <div class="button-row">
            <button class="danger" type="button" data-delete-report="${report.id}" data-company-id="${report.company_id}" data-report-title="${escapeAttr(report.title)}">Delete Report</button>
            ${reportSubmitButtons(report)}
          </div>
        </div>
        <div class="panel-body form-grid">
          <label>Title <input name="title" value="${escapeAttr(report.title)}" /></label>
          <label>Report month <input name="report_month" value="${escapeAttr(report.report_month || "")}" /></label>
          <label>Result <select name="result">${resultOptions(report.result)}</select></label>
        </div>
      </section>

      <section class="panel">
        <div class="panel-body">
          ${schema.sections.map((section) => reportSection(section, report)).join("")}
        </div>
      </section>

      ${reportQualityBanner(report)}
      <section class="panel">
        <div class="panel-header">
          <div>
            <h3>Decision Summary</h3>
            <p class="muted">This controls dashboard position, watchlist summary, archive summary, and monitoring rules.</p>
          </div>
        </div>
        <div class="panel-body grid">
          <label class="full">Summary <textarea name="summary" rows="4">${escapeHtml(report.summary || "")}</textarea></label>
          <label class="full">Watchlist conditions <textarea name="watchlist_conditions" rows="3">${escapeHtml(report.watchlist_conditions || "")}</textarea></label>
          <label class="full">Non-objective monitoring rules <textarea name="watchlist_subjective_rules" rows="3">${escapeHtml(report.watchlist_subjective_rules || "")}</textarea></label>
          <div class="grid" id="objective-rules">
            <div class="panel-header">
              <div>
                <h3>Objective Monitoring Rules</h3>
                <p class="muted">Define the rule here. Update current values and runtime notes from Monitoring.</p>
              </div>
              <button class="secondary" type="button" id="add-objective-rule">Add Rule</button>
            </div>
            <div id="objective-rule-list">
              ${(report.watchlist_objective_rules || []).map((rule) => objectiveRuleRow(rule)).join("")}
            </div>
          </div>
          <label class="full">Archive red flags <textarea name="archive_red_flags" rows="3">${escapeHtml(report.archive_red_flags || "")}</textarea></label>
          <label>Next action <input name="next_action" value="${escapeAttr(report.next_action || "")}" /></label>
          <label>Recommended reassessment date <input name="review_date" type="date" value="${escapeAttr(report.review_date || "")}" /></label>
          <div class="button-row">
            ${reportSubmitButtons(report, { includeBack: true })}
          </div>
        </div>
      </section>
    </form>
  `;
  initializeAnswerableReportSections(report, schema);
  const reportForm = content.querySelector("#report-form");
  reportForm.addEventListener("submit", saveReport);
  bindCompletionPreviewTracking(reportForm);
  bindCompletionPreviewButton();
  content.querySelectorAll("[data-company-return]").forEach((button) => {
    button.addEventListener("click", () => openCompany(Number(button.dataset.companyReturn)));
  });
  bindDeleteReportButtons();
  content.querySelector("#add-objective-rule").addEventListener("click", () => {
    content.querySelector("#objective-rule-list").insertAdjacentHTML("beforeend", objectiveRuleRow({}));
    clearCompletionPreview();
  });
  if (!content.querySelector("#objective-rule-list").children.length) {
    content.querySelector("#objective-rule-list").innerHTML = objectiveRuleRow({});
  }
}

function isDataCollectionReport(report) {
  return report.stage_name === "Data Collection";
}

function renderDataCollectionReportEditor(report) {
  const template = report.template;
  const schema = template.schema || { sections: [] };
  content.innerHTML = `
    <form id="report-form" class="grid data-collection-report">
      <section class="panel">
        <div class="panel-header detail-head">
          <div>
            <button class="secondary" type="button" data-company-return="${report.company_id}">Back to Company</button>
            <p class="eyebrow">${escapeHtml(report.stage_name)}</p>
            <h3 class="company-title">${escapeHtml(report.title)}</h3>
            <p class="muted">Collect the source pack here. Imported sources become part of the company-wide source library and get an LLM-readable text view when possible.</p>
          </div>
          <div class="button-row">
            <button class="danger" type="button" data-delete-report="${report.id}" data-company-id="${report.company_id}" data-report-title="${escapeAttr(report.title)}">Delete Report</button>
            ${reportSubmitButtons(report)}
          </div>
        </div>
        <div class="panel-body form-grid">
          <label>Title <input name="title" value="${escapeAttr(report.title)}" /></label>
          <label>Report month <input name="report_month" value="${escapeAttr(report.report_month || "")}" /></label>
          <label>Result <select name="result">${resultOptions(report.result)}</select></label>
        </div>
      </section>

      ${dataCollectionSourcesPanel(report)}
      ${dataCollectionAgentPanel(report)}
      ${reportQualityBanner(report)}

      <section class="panel">
        <div class="panel-body">
          ${schema.sections.map((section) => dataCollectionSection(section, report)).join("")}
        </div>
      </section>

      ${genericDecisionSummaryPanel(report)}
    </form>
    ${sourceDialogMarkup(report)}
    ${sourceDeleteDialogMarkup()}
    ${documentPreviewDialogMarkup()}
  `;
  initializeAnswerableReportSections(report, schema);
  bindDataCollectionReportEvents(report);
}

function dataCollectionSourcesPanel(report) {
  const groups = reportSourceGroups(report);
  return `
    <details class="panel report-collapsible-panel sources-panel">
      ${collapsiblePanelSummary(
        "Company Source Library",
        "Collected sources stay available to Screening and later reports. For website-only evidence, save the live link and a stored snapshot so later stages can reuse the same source object.",
        sourceVisualization(groups.allAvailableSources),
      )}
      <div class="panel-body grid">
        <div class="button-row">
          <button class="primary" type="button" id="source-add-button">Add Source</button>
        </div>
        ${sourceGroupSection("This Report’s Sources", "Edit or delete only the sources created in this report.", groups.reportSources, {
          editable: true,
          emptyMessage: "No sources created in this report yet.",
        })}
        ${sourceGroupSection("Suggested Company Sources", "Prior-stage cited sources rank first for reuse when the company already has a source library.", groups.suggestedSources, {
          emptyMessage: "No suggested company sources yet.",
        })}
        ${sourceGroupSection("All Company Sources", "Remaining company-library sources can be cited directly without re-uploading duplicates.", groups.remainingCompanySources, {
          emptyMessage: "No additional company sources in the library.",
        })}
      </div>
    </details>
  `;
}

function dataCollectionAgentPanel(report) {
  const contract = report.agent_contract;
  if (!contract) return "";
  const completion = contract.completion || {};
  const tone = completion.ready_for_screening ? "green" : completionStatusTone(completion.status);
  return `
    <details class="panel report-collapsible-panel">
      ${collapsiblePanelSummary(
        "LLM Contract",
        "Machine-readable instructions for agents that need to finish Data Collection without relying on hidden UI behavior.",
        `<span class="pill ${tone}">${escapeHtml(completion.status || "unknown")}</span>`,
      )}
      <div class="panel-body grid">
        <div class="rule-stack">
          <span class="pill">Sources ${escapeHtml(String(completion.source_count || 0))}</span>
          <span class="pill">LLM-ready ${escapeHtml(String(completion.normalized_ready_source_count || 0))}</span>
          <span class="pill">${completion.ready_for_screening ? "Ready for Screening" : "Not ready yet"}</span>
        </div>
        <div class="source-guidance-box">
          <strong>Agent Guidance</strong>
          <ul>${(contract.guidance || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>
        </div>
        ${dataCollectionCompletionBlock(completion)}
        <details class="source-guidance">
          <summary>Machine contract JSON</summary>
          <pre class="template-copy">${escapeHtml(JSON.stringify(contract, null, 2))}</pre>
        </details>
      </div>
    </details>
  `;
}

function dataCollectionCompletionBlock(completion) {
  const missingFields = completion.missing_fields || [];
  const missingRows = completion.missing_coverage_rows || [];
  const warnings = completion.warnings || [];
  if (!missingFields.length && !missingRows.length && !warnings.length) {
    return `<div class="source-guidance-box"><strong>Completion</strong><p class="muted">No blocking gaps detected in the Data Collection contract.</p></div>`;
  }
  return `
    <div class="source-guidance-box warning-box">
      <strong>Open Gaps</strong>
      ${missingRows.length ? `<p class="muted">Coverage rows still missing: ${escapeHtml(missingRows.join(", "))}</p>` : ""}
      ${missingFields.length ? `<ul>${missingFields.map((field) => `<li>${escapeHtml(field.section_title)}: ${escapeHtml(field.label)}</li>`).join("")}</ul>` : ""}
      ${warnings.length ? `<div class="muted">${warnings.map((warning) => escapeHtml(warning)).join("<br>")}</div>` : ""}
    </div>
  `;
}

function screeningAgentPanel(report) {
  const contract = report.agent_contract;
  if (!contract || contract.report_kind !== "screening") return "";
  const completion = contract.completion || {};
  const tone = completionStatusTone(completion.status);
  return `
    <details class="panel report-collapsible-panel">
      ${collapsiblePanelSummary(
        "LLM Contract",
        "Machine-readable instructions for agents that need to finish Screening without relying on hidden UI behavior.",
        `<span class="pill ${tone}">${escapeHtml(completion.status || "unknown")}</span>`,
      )}
      <div class="panel-body grid">
        <div class="rule-stack">
          <span class="pill">Sources ${escapeHtml(String(completion.source_count || 0))}</span>
          <span class="pill">LLM-ready ${escapeHtml(String(completion.normalized_ready_source_count || 0))}</span>
          <span class="pill">${escapeHtml(completion.final_decision || "No final decision")}</span>
        </div>
        <div class="source-guidance-box">
          <strong>Agent Guidance</strong>
          <ul>${(contract.guidance || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>
        </div>
        ${screeningCompletionBlock(completion)}
        <details class="source-guidance">
          <summary>Machine contract JSON</summary>
          <pre class="template-copy">${escapeHtml(JSON.stringify(contract, null, 2))}</pre>
        </details>
      </div>
    </details>
  `;
}

function screeningCompletionBlock(completion) {
  const missingFields = completion.missing_fields || [];
  const missingSourceLinks = completion.missing_source_links || [];
  const requirements = completion.decision_requirements || [];
  const warnings = completion.warnings || [];
  if (!missingFields.length && !missingSourceLinks.length && !requirements.length && !warnings.length) {
    return `<div class="source-guidance-box"><strong>Completion</strong><p class="muted">No blocking gaps detected in the Screening contract.</p></div>`;
  }
  return `
    <div class="source-guidance-box warning-box">
      <strong>Open Gaps</strong>
      ${requirements.length ? `<p class="muted">${escapeHtml(requirements.join(" "))}</p>` : ""}
      ${missingFields.length ? `<ul>${missingFields.map((field) => `<li>${escapeHtml(field.section_title)}: ${escapeHtml(field.label)}</li>`).join("")}</ul>` : ""}
      ${missingSourceLinks.length ? `<ul>${missingSourceLinks.map((field) => `<li>Missing source links: ${escapeHtml(field.section_title)}: ${escapeHtml(field.label)}</li>`).join("")}</ul>` : ""}
      ${warnings.length ? `<div class="muted">${warnings.map((warning) => escapeHtml(warning)).join("<br>")}</div>` : ""}
    </div>
  `;
}

function reportSubmitButtons(report, { includeBack = false } = {}) {
  return `
    <button class="secondary" type="submit">Save Draft</button>
    <button class="primary" type="submit" data-finalize-report="1">Finalize Report</button>
    ${includeBack ? `<button class="secondary" type="button" data-company-return="${report.company_id}">Back to Company</button>` : ""}
  `;
}

function genericDecisionSummaryPanel(report) {
  return `
    <section class="panel">
      <div class="panel-header">
        <div>
          <h3>Decision Summary</h3>
          <p class="muted">This controls dashboard position, watchlist summary, archive summary, and monitoring rules.</p>
        </div>
      </div>
      <div class="panel-body grid">
        <label class="full">Summary <textarea name="summary" rows="4">${escapeHtml(report.summary || "")}</textarea></label>
        <label class="full">Watchlist conditions <textarea name="watchlist_conditions" rows="3">${escapeHtml(report.watchlist_conditions || "")}</textarea></label>
        <label class="full">Non-objective monitoring rules <textarea name="watchlist_subjective_rules" rows="3">${escapeHtml(report.watchlist_subjective_rules || "")}</textarea></label>
        <div class="grid" id="objective-rules">
          <div class="panel-header">
            <div>
              <h3>Objective Monitoring Rules</h3>
              <p class="muted">Define the rule here. Update current values and runtime notes from Monitoring.</p>
            </div>
            <button class="secondary" type="button" id="add-objective-rule">Add Rule</button>
          </div>
          <div id="objective-rule-list">
            ${(report.watchlist_objective_rules || []).map((rule) => objectiveRuleRow(rule)).join("")}
          </div>
        </div>
        <label class="full">Archive red flags <textarea name="archive_red_flags" rows="3">${escapeHtml(report.archive_red_flags || "")}</textarea></label>
        <label>Next action <input name="next_action" value="${escapeAttr(report.next_action || "")}" /></label>
        <label>Recommended reassessment date <input name="review_date" type="date" value="${escapeAttr(report.review_date || "")}" /></label>
        <div class="button-row">
          ${reportSubmitButtons(report, { includeBack: true })}
        </div>
      </div>
    </section>
  `;
}

function bindDataCollectionReportEvents(report) {
  const reportForm = content.querySelector("#report-form");
  reportForm.addEventListener("submit", saveReport);
  bindCompletionPreviewTracking(reportForm);
  bindCompletionPreviewButton();
  content.querySelectorAll("[data-company-return]").forEach((button) => {
    button.addEventListener("click", () => openCompany(Number(button.dataset.companyReturn)));
  });
  bindDeleteReportButtons();
  content.querySelector("#add-objective-rule").addEventListener("click", () => {
    content.querySelector("#objective-rule-list").insertAdjacentHTML("beforeend", objectiveRuleRow({}));
    clearCompletionPreview();
  });
  if (!content.querySelector("#objective-rule-list").children.length) {
    content.querySelector("#objective-rule-list").innerHTML = objectiveRuleRow({});
  }
  content.querySelector("#source-import-button").addEventListener("click", createReportSource);
  content.querySelector("#source-add-button").addEventListener("click", () => openSourceDialog());
  content.querySelectorAll("[data-edit-source]").forEach((button) => {
    button.addEventListener("click", () => openSourceDialog(Number(button.dataset.editSource)));
  });
  content.querySelectorAll("[data-delete-source]").forEach((button) => {
    button.addEventListener("click", () => openSourceDeleteDialog(Number(button.dataset.deleteSource)));
  });
  content.querySelectorAll("[data-close-source-dialog]").forEach((button) => {
    button.addEventListener("click", () => content.querySelector("#source-dialog").close());
  });
  content.querySelector("#source-dialog").addEventListener("click", (event) => {
    if (event.target === event.currentTarget) event.currentTarget.close();
  });
  content.querySelectorAll("[data-close-source-delete]").forEach((button) => {
    button.addEventListener("click", () => content.querySelector("#source-delete-dialog").close());
  });
  content.querySelector("#source-delete-dialog").addEventListener("click", (event) => {
    if (event.target === event.currentTarget) event.currentTarget.close();
  });
  content.querySelector("#source-delete-confirm").addEventListener("click", confirmDeleteReportSource);
  bindPreviewButtons();
}

function reportSection(section, report) {
  return `
    <div class="report-section" data-section-id="${section.id}">
      <div class="detail-head">
        <div>
          <h3 class="section-title">${escapeHtml(section.title)}</h3>
          <details class="source-guidance">
            <summary>Source guidance</summary>
            <pre class="template-copy">${escapeHtml(section.body_markdown || "")}</pre>
          </details>
        </div>
      </div>
      <div class="section-tools">
        <div>
          <span class="muted">Quality spectrum</span>
          ${ratingStrip(`rating-${section.id}`, report.section_ratings?.[section.id])}
        </div>
        <label>Data quality
          <select name="dq-${section.id}" data-data-quality="${section.id}">
            ${qualityOptions(report.data_quality?.[section.id])}
          </select>
        </label>
      </div>
      <div class="field-grid">
        ${(section.fields || []).map((field) => fieldInput(field, report)).join("")}
      </div>
    </div>
  `;
}

function dataCollectionSection(section, report) {
  return `
    <div class="report-section" data-section-id="${section.id}">
      <div class="detail-head">
        <div>
          <h3 class="section-title">${escapeHtml(section.title)}</h3>
          <details class="source-guidance">
            <summary>Template guidance</summary>
            <pre class="template-copy">${escapeHtml(section.body_markdown || "")}</pre>
          </details>
        </div>
      </div>
      <div class="field-grid">
        ${(section.fields || []).map((field) => fieldInput(field, report)).join("")}
      </div>
    </div>
  `;
}

function fieldInput(field, report) {
  const isMetric = field.kind === "metric" || field.kind === "number";
  const value = fieldValue(field, report);
  const full = field.kind === "textarea" ? "full" : "";
  const attrs = `data-field-id="${field.id}" data-field-kind="${field.kind}"`;
  const wrapperAttrs = reportFieldWrapperAttrs(field, report);
  if (field.kind === "select") {
    const options = [`<option value=""></option>`].concat((field.options || []).map((item) => {
      const selected = String(value) === String(item) ? "selected" : "";
      return `<option value="${escapeAttr(item)}" ${selected}>${escapeHtml(item)}</option>`;
    }));
    return `<label class="${full}" ${wrapperAttrs}>${escapeHtml(field.label)} <select ${attrs}>${options.join("")}</select></label>`;
  }
  if (field.kind === "textarea") {
    return `<label class="${full}" ${wrapperAttrs}>${escapeHtml(field.label)} <textarea rows="4" ${attrs}>${escapeHtml(value)}</textarea></label>`;
  }
  if (field.kind === "date") {
    return `<label ${wrapperAttrs}>${escapeHtml(field.label)} <input type="date" value="${escapeAttr(value)}" ${attrs} /></label>`;
  }
  if (isMetric) {
    const max = field.max ? ` max="${field.max}"` : "";
    return `<label ${wrapperAttrs}>${escapeHtml(field.label)} <input type="number" step="any" value="${escapeAttr(value)}" ${attrs}${max} /></label>`;
  }
  return `<label ${wrapperAttrs}>${escapeHtml(field.label)} <input value="${escapeAttr(value)}" ${attrs} /></label>`;
}

function ratingStrip(name, value) {
  const labels = ["Bad", "Weak", "Ok", "Good", "Excellent"];
  return `
    <div class="rating-strip">
      ${labels.map((label, index) => {
        const rating = index + 1;
        const checked = Number(value) === rating ? "checked" : "";
        return `<label><input type="radio" name="${escapeAttr(name)}" value="${rating}" ${checked} /><span>${label}</span></label>`;
      }).join("")}
    </div>
  `;
}

function qualityOptions(selected) {
  const options = [
    ["", ""],
    ["1", "1 - Thin"],
    ["2", "2 - Limited"],
    ["3", "3 - Adequate"],
    ["4", "4 - Strong"],
    ["5", "5 - Primary-source strong"],
  ];
  return options.map(([value, label]) => `<option value="${value}" ${String(selected || "") === value ? "selected" : ""}>${label}</option>`).join("");
}

function isScreeningReport(report) {
  if (report.stage_name !== "Screening") return false;
  const titles = new Set((report.template?.schema?.sections || []).map((section) => section.title));
  return titles.has("Part I. Fast Kill Screen")
    && titles.has("Part VII. What Must Be True / What To Verify")
    && titles.has("Final Decision");
}

function renderScreeningReportEditor(report) {
  const template = report.template;
  const schema = template.schema || { sections: [], fields: [] };
  const sections = schema.sections.filter((section) => !skipScreeningSection(section.title));
  const selectedFinalDecision = finalDecisionFromReport(report, schema);
  content.innerHTML = `
    <form id="report-form" class="grid screening-report">
      <section class="panel">
        <div class="panel-header detail-head">
          <div>
            <button class="secondary" type="button" data-company-return="${report.company_id}">Back to Company</button>
            <p class="eyebrow">${escapeHtml(report.stage_name)}</p>
            <h3 class="company-title">${escapeHtml(report.title)}</h3>
            <p class="muted">Screening questionnaire. Sources, field notes, and citations are saved with this report.</p>
          </div>
          <div class="button-row">
            <button class="danger" type="button" data-delete-report="${report.id}" data-company-id="${report.company_id}" data-report-title="${escapeAttr(report.title)}">Delete Report</button>
            ${reportSubmitButtons(report)}
          </div>
        </div>
        <div class="panel-body form-grid compact-form">
          <label>Title <input name="title" value="${escapeAttr(report.title)}" /></label>
          <label>Report month <input name="report_month" value="${escapeAttr(report.report_month || "")}" /></label>
          <input type="hidden" name="result" value="${escapeAttr(resultValueForFinalDecision(selectedFinalDecision) || "Draft")}" />
          <input type="hidden" name="review_date" value="${escapeAttr(report.review_date || "")}" />
        </div>
        ${reportQualityBanner(report)}
      </section>

      ${screeningSourcesPanel(report)}
      ${screeningAgentPanel(report)}

      <section class="panel">
        <div class="panel-body">
          ${sections.map((section) => screeningSection(section, report, schema)).join("")}
        </div>
      </section>

      ${screeningDecisionPanel(report)}
    </form>
    ${fieldPopoverMarkup()}
    ${sourceDialogMarkup(report)}
    ${sourceDeleteDialogMarkup()}
    ${documentPreviewDialogMarkup()}
  `;
  initializeAnswerableReportSections(report, schema);
  bindScreeningReportEvents(report);
}

const REPORT_SECTION_SUMMARY_LABELS = [
  "decision",
  "final decision",
  "fast kill result",
  "evidence result",
  "interaction read",
  "business category result",
  "business quality result",
  "business type result",
  "failure-mode result",
  "management category result",
  "capital allocation result",
  "culture read",
  "governance result",
  "financial snapshot result",
  "valuation read",
  "fragility read",
  "execution pattern result",
  "munger check result",
  "result",
];

function initializeAnswerableReportSections(report, schema) {
  decorateAnswerableReportSections(report, schema);
  installAnswerableSectionToolbars();
  refreshAnswerableSectionSummaries();
}

function decorateAnswerableReportSections(report, schema) {
  const sectionsById = new Map((schema.sections || []).map((section) => [String(section.id), section]));
  content.querySelectorAll(".report-section[data-section-id]").forEach((node) => {
    if (node.matches("details")) return;
    const section = sectionsById.get(String(node.dataset.sectionId));
    if (!section) return;
    const details = document.createElement("details");
    details.className = `${node.className} report-section-toggle${Number(section.level || 0) > 1 ? " report-section-subsection" : ""}`;
    details.dataset.sectionId = String(section.id);
    details.dataset.sectionLevel = String(section.level || 0);
    details.dataset.answerableToggle = "1";
    details.innerHTML = `
      <summary class="report-section-summary">
        <span class="report-toggle-summary-main">
          <span class="report-toggle-caret" aria-hidden="true"></span>
          <span class="report-section-summary-title">${escapeHtml(section.title)}</span>
        </span>
        ${answerableSectionSummaryMarkup(section, report)}
      </summary>
      <div class="report-section-body"></div>
    `;
    const body = details.querySelector(".report-section-body");
    while (node.firstChild) body.appendChild(node.firstChild);
    cleanupDecoratedSectionBody(body);
    node.replaceWith(details);
  });
}

function cleanupDecoratedSectionBody(body) {
  const header = body.firstElementChild;
  if (!header || !(header.classList?.contains("section-heading") || header.classList?.contains("detail-head"))) return;
  header.querySelector(".section-title")?.remove();
  [...header.children].forEach((child) => {
    if (!child.children.length && !child.textContent.trim()) child.remove();
  });
  if (!header.children.length && !header.textContent.trim()) header.remove();
}

function installAnswerableSectionToolbars() {
  content.querySelectorAll(".panel > .panel-body").forEach((body) => {
    const answerableSections = [...body.children].filter((node) => node.matches?.('[data-answerable-toggle="1"]'));
    if (!answerableSections.length || body.querySelector(".report-section-toolbar")) return;
    body.insertAdjacentHTML("afterbegin", reportSectionToolbarMarkup());
    const collapse = body.querySelector("[data-collapse-answer-sections]");
    const expand = body.querySelector("[data-expand-answer-sections]");
    collapse?.addEventListener("click", () => setAnswerableSectionsOpen(body, false));
    expand?.addEventListener("click", () => setAnswerableSectionsOpen(body, true));
  });
}

function reportSectionToolbarMarkup() {
  return `
    <div class="report-section-toolbar">
      <div class="button-row">
        <button class="secondary" type="button" data-collapse-answer-sections="1">Collapse All</button>
        <button class="secondary" type="button" data-expand-answer-sections="1">Expand All</button>
      </div>
    </div>
  `;
}

function setAnswerableSectionsOpen(container, open) {
  container.querySelectorAll('[data-answerable-toggle="1"]').forEach((section) => {
    section.open = open;
  });
}

function answerableSectionSummaryField(section) {
  const fields = section.fields || [];
  for (const label of REPORT_SECTION_SUMMARY_LABELS) {
    const match = fields.find((field) => String(field.label || "").trim().toLowerCase() === label);
    if (match) return match;
  }
  const resultFields = fields.filter(isResultField);
  if (resultFields.length === 1) return resultFields[0];
  const topLevelResultFields = resultFields.filter((field) => !String(field.label || "").includes(" - "));
  return topLevelResultFields.length === 1 ? topLevelResultFields[0] : null;
}

function answerableSectionSummaryMarkup(section, report) {
  const field = answerableSectionSummaryField(section);
  if (!field) return "";
  return `
    <span class="report-section-summary-preview" data-section-summary-field="${escapeAttr(field.id)}">
      <span class="report-section-summary-label">${escapeHtml(displayFieldLabel(field.label))}</span>
      <span class="report-section-summary-value" data-section-summary-value>${answerableSectionSummaryValueMarkup(field, fieldValue(field, report))}</span>
    </span>
  `;
}

function answerableSectionSummaryValueMarkup(field, value) {
  const text = String(value ?? "").trim();
  if (!text) return `<span class="muted">Not answered</span>`;
  if (field.kind === "select") {
    return `<span class="section-summary-pill tone-${escapeAttr(spectrumTone(text))}">${escapeHtml(text)}</span>`;
  }
  return `<span class="report-section-summary-text">${escapeHtml(text)}</span>`;
}

function currentRenderedFieldValue(fieldId) {
  const inputs = [...content.querySelectorAll(`[data-field-id="${CSS.escape(fieldId)}"]`)];
  if (!inputs.length) return null;
  const checkedRadio = inputs.find((input) => input.type === "radio" && input.checked);
  if (checkedRadio) return checkedRadio.value;
  const checkbox = inputs.find((input) => input.type === "checkbox");
  if (checkbox) return checkbox.checked ? "Yes" : "";
  const input = inputs[0];
  return String(input.value || "").trim();
}

function refreshAnswerableSectionSummaries() {
  content.querySelectorAll("[data-section-summary-field]").forEach((preview) => {
    const fieldId = preview.dataset.sectionSummaryField;
    const field = currentReportField(fieldId);
    if (!field) return;
    const renderedValue = currentRenderedFieldValue(fieldId);
    const value = renderedValue === null ? fieldValue(field, state.currentReport || {}) : renderedValue;
    const valueNode = preview.querySelector("[data-section-summary-value]");
    if (valueNode) valueNode.innerHTML = answerableSectionSummaryValueMarkup(field, value);
  });
}

function collapsiblePanelSummary(title, description, extra = "") {
  return `
    <summary class="panel-header report-collapsible-summary">
      <div class="report-collapsible-summary-main">
        <span class="report-toggle-caret" aria-hidden="true"></span>
        <div>
          <h3>${escapeHtml(title)}</h3>
          ${description ? `<p class="muted">${escapeHtml(description)}</p>` : ""}
        </div>
      </div>
      ${extra}
    </summary>
  `;
}

function skipScreeningSection(title) {
  return [
    "Stock Candidate Screening Questionnaire v5",
    "Stock Candidate Screening Questionnaire v4",
    "Core Rules",
    "Category Options",
    "Exceptional Compounder",
    "Good Predictable Business",
    "Cyclical / Commodity / Asset-Heavy Business",
    "Financial / Insurer",
    "Special Situation",
    "Too Hard",
  ].includes(title);
}

function availableSources(report) {
  return reportSourceGroups(report).allAvailableSources;
}

function screeningSourcesPanel(report) {
  const groups = reportSourceGroups(report);
  return `
    <details class="panel report-collapsible-panel sources-panel">
      ${collapsiblePanelSummary(
        "Source Library",
        "Reuse suggested company sources first. Create a new source only when the evidence is not already in the company library.",
        sourceVisualization(groups.allAvailableSources),
      )}
      <div class="panel-body grid">
        <div class="button-row">
          <button class="primary" type="button" id="source-add-button">Add Source</button>
        </div>
        ${sourceGroupSection("This Report’s Sources", "Edit or delete only the sources created in this report.", groups.reportSources, {
          editable: true,
          emptyMessage: "No sources created in this report yet.",
        })}
        ${sourceGroupSection("Suggested Company Sources", "Cited upstream sources and latest-stage evidence are ranked here for reuse first.", groups.suggestedSources, {
          emptyMessage: "No suggested upstream sources yet.",
        })}
        ${sourceGroupSection("All Company Sources", "Remaining company-library sources are still available for citation without creating duplicates.", groups.remainingCompanySources, {
          emptyMessage: "No additional company sources in the library.",
        })}
      </div>
    </details>
  `;
}

function sourceVisualization(sources) {
  if (!sources.length) return `<span class="pill">0 sources</span>`;
  const counts = sources.reduce((acc, source) => {
    const grade = source.evidence_grade || "U";
    acc[grade] = (acc[grade] || 0) + 1;
    return acc;
  }, {});
  return `
    <div class="source-viz">
      ${Object.entries(counts).map(([grade, count]) => `<span class="source-grade grade-${escapeAttr(grade)}" title="${escapeAttr(evidenceGradeLabel(grade))}">${escapeHtml(grade)} ${count}</span>`).join("")}
    </div>
  `;
}

function sourceRows(sources, options = {}) {
  const editable = Boolean(options.editable);
  const emptyMessage = options.emptyMessage || "No sources imported yet.";
  if (!sources.length) return `<div class="empty-state">${escapeHtml(emptyMessage)}</div>`;
  return `
    <div class="table-wrap">
      <table class="source-table">
        <thead><tr><th>Source</th><th>Type</th><th>Evidence</th><th>Reuse</th><th>Tags</th><th>Citation</th><th>Open</th>${editable ? "<th></th>" : ""}</tr></thead>
        <tbody>
          ${sources.map((source) => `
            <tr>
              <td><strong>${escapeHtml(source.title)}</strong>${source.notes ? `<br><span class="muted">${escapeHtml(source.notes)}</span>` : ""}</td>
              <td>${escapeHtml(source.source_type || "")}<br><span class="muted">${escapeHtml(source.confidence || "No confidence")}</span>${sourceStageContext(source) ? `<br><span class="muted">${escapeHtml(sourceStageContext(source))}</span>` : ""}</td>
              <td><span class="source-grade grade-${escapeAttr(source.evidence_grade || "U")}">${escapeHtml(evidenceGradeLabel(source.evidence_grade || "U"))}</span></td>
              <td>${llmSourceBadge(source)}${sourceCapabilityRow(source)}${source.normalized_preview ? `<br><button type="button" class="small-button" data-preview-document="${source.document_id}">Preview</button>` : ""}</td>
              <td><div class="tag-row">${(source.tags || []).map((tag) => `<span class="pill">${escapeHtml(tag)}</span>`).join("")}</div></td>
              <td>${escapeHtml(source.citation || "")}</td>
              <td>${sourceOpenLinks(source)}</td>
              ${editable ? `
                <td>
                  <div class="button-row">
                    <button type="button" class="small-button" data-edit-source="${source.id}">Edit</button>
                    <button type="button" class="small-button danger" data-delete-source="${source.id}">Delete</button>
                  </div>
                </td>
              ` : ""}
            </tr>
          `).join("")}
        </tbody>
      </table>
    </div>
  `;
}

function sourceDialogMarkup(report) {
  return `
    <dialog id="source-dialog" class="floating-box">
      <div class="floating-box-inner">
        <div class="modal-header">
          <div>
            <h3 id="source-dialog-title">Add Source</h3>
            <p class="muted">Import links, files, source grades, and tags. Saved sources stay available across the whole company record.</p>
          </div>
          <button type="button" class="icon-button" data-close-source-dialog>x</button>
        </div>
        <div class="source-import-form" id="source-import-form">
          <input type="hidden" name="report_id" value="${report.id}" />
          <input type="hidden" name="id" value="" />
          <input type="hidden" name="document_id" value="" />
          <div class="source-guidance-box warning-box">
            <strong>Website snapshot rule</strong>
            <p class="muted">URL-only sources are degraded and will block finalization. Read this before saving a website source without a snapshot.</p>
            <ul>
              <li>Save the live URL.</li>
              <li>Upload a durable snapshot in the same source whenever possible.</li>
              <li>Use HTML when structure matters, Markdown or text when you already extracted the visible text, and CSV or spreadsheet files for table-heavy pages.</li>
            </ul>
          </div>
          <div class="form-grid">
            <label>Title <input name="title" placeholder="FY2025 10-K" required /></label>
            <label>Type <select name="source_type">${SOURCE_TYPES.map((type) => `<option>${escapeHtml(type)}</option>`).join("")}</select></label>
            <label>Evidence grade <select name="evidence_grade">${sourceEvidenceOptions("")}</select></label>
            <label>Confidence <select name="confidence">${confidenceOptions("")}</select></label>
          </div>
          <div class="form-grid">
            <label>URL <input name="url" placeholder="https://..." /></label>
            <label>Default citation <input name="citation" placeholder="p. 234, Q2 call, slide 18" /></label>
            <label>Tags <input name="tags" placeholder="moat, margins, balance sheet" /></label>
            <label>File <input name="file" type="file" /></label>
          </div>
          <div class="source-guidance-box warning-box hidden" id="source-link-only-panel">
            <strong>URL-only source requires explanation</strong>
            <p class="muted">This source has a live URL but no stored snapshot. It will be marked <strong>Link Only</strong> until a durable artifact is uploaded.</p>
            <label class="checkbox-row">
              <input name="snapshot_guidance_acknowledged" type="checkbox" />
              <span>I read the snapshot upload guidance above and understand this source stays degraded until a snapshot is uploaded.</span>
            </label>
            <label>Why is this still link-only right now?
              <textarea name="link_only_reason" rows="3" placeholder="Explain why the snapshot is missing and what should happen next."></textarea>
            </label>
          </div>
          <label>Notes <textarea name="notes" rows="2" placeholder="What this source is useful for"></textarea></label>
        </div>
        <div class="modal-actions">
          <button type="button" class="secondary" data-close-source-dialog>Cancel</button>
          <button class="primary" type="button" id="source-import-button">Save Source</button>
        </div>
      </div>
    </dialog>
  `;
}

function sourceDeleteDialogMarkup() {
  return `
    <dialog id="source-delete-dialog" class="floating-box confirm-dialog">
      <div class="floating-box-inner">
        <div class="modal-header">
          <div>
            <h3>Delete Source</h3>
            <p class="muted" id="source-delete-message">This source will be removed from the report and unlinked from cited answers.</p>
          </div>
          <button type="button" class="icon-button" data-close-source-delete>x</button>
        </div>
        <div class="modal-actions">
          <button type="button" class="secondary" data-close-source-delete>Cancel</button>
          <button type="button" class="danger" id="source-delete-confirm">Delete Source</button>
        </div>
      </div>
    </dialog>
  `;
}

function documentPreviewDialogMarkup() {
  return `
    <dialog id="document-preview-dialog" class="floating-box">
      <div class="floating-box-inner">
        <div class="modal-header">
          <div>
            <h3 id="document-preview-title">Source Preview</h3>
            <p class="muted" id="document-preview-meta">LLM-ready source preview.</p>
          </div>
          <button type="button" class="icon-button" data-close-document-preview>x</button>
        </div>
        <div class="preview-body">
          <pre class="template-copy" id="document-preview-text"></pre>
        </div>
        <div class="modal-actions" id="document-preview-actions">
          <button type="button" class="secondary" data-close-document-preview>Close</button>
        </div>
      </div>
    </dialog>
  `;
}

function documentUploadDialogMarkup(company) {
  return `
    <dialog id="document-upload-dialog" class="floating-box confirm-dialog">
      <div class="floating-box-inner">
        <div class="modal-header">
          <div>
            <h3>Upload Document</h3>
            <p class="muted">Attach filings, slides, notes, or data files to the company record or a specific report.</p>
          </div>
          <button type="button" class="icon-button" data-close-upload-dialog>x</button>
        </div>
        <form class="grid" id="upload-form">
          <input type="hidden" name="company_id" value="${company.id}" />
          <label>Attach to report <select name="report_id">
            <option value="">Company-level document</option>
            ${(company.reports || []).map((report) => `<option value="${report.id}">${escapeHtml(report.title)}</option>`).join("")}
          </select></label>
          <label>File <input name="file" type="file" required /></label>
          <label>Notes <textarea name="notes" rows="3"></textarea></label>
          <div class="modal-actions">
            <button type="button" class="secondary" data-close-upload-dialog>Cancel</button>
            <button class="primary" type="submit">Upload Document</button>
          </div>
        </form>
      </div>
    </dialog>
  `;
}

function screeningSection(section, report, schema) {
  if (section.title === "Basic Inputs") return basicInputsSection(section, report);
  if (section.title === "Part I. Fast Kill Screen") return fastKillSection(section, report);
  if (isHardGateSection(section, schema)) return hardGateSection(section, report);
  if (section.title === "Part IV. Business Quality Snapshot") return groupedTableSection(section, report, ["Rating", "Evidence Grade", "Source", "Confidence", "Notes"]);
  if (section.title === "Moat Hypothesis") return standardScreeningSection(section, report, { resultSpectrumLabels: ["Business Quality Result"], compactTextareas: true });
  if (section.title === "1. Returns, Margins, And Capital Intensity") return returnsMarginsSection(section, report);
  if (section.title === "2. Owner Earnings Sanity Check") return ownerSanitySection(section, report);
  if (section.title === "3. Per-Share Value Creation And Retained-Capital Test") return perShareSection(section, report);
  if (section.title === "4. Balance Sheet Stress Snapshot") return balanceSheetSection(section, report);
  if (section.title.startsWith("Part VI.") || isPartVISection(section, schema)) return valuationSection(section, report);
  if (section.title === "Part VII. What Must Be True / What To Verify") return whatMustBeTrueSection(section, report);
  if (section.title === "2. Psychology And Bias Audit") return biasAuditSection(section, report);
  if (section.title === "Part IX. Business Category And Next Underwriting Standard") return businessCategorySection(section, report, schema);
  if (section.title === "Hard Gate Summary") return hardGateSummarySection(section, report, schema);
  if (section.title === "Quality Summary") return groupedTableSection(section, report, ["Rating", "Confidence"]);
  if (["If It Passes Screening", "If It Goes To Watchlist", "If It Is Archived", "If It Is Redirected"].includes(section.title)) return "";
  if (section.title === "Final Decision") return standardScreeningSection(section, report, { compact: true, resultSpectrumLabels: ["Decision"] });
  if (section.title === "One-Page Screening Conclusion") return onePageConclusionSection(section, report, schema);
  return standardScreeningSection(section, report, { compactTextareas: COMPACT_TEXTAREA_SECTIONS.has(section.title) });
}

function standardScreeningSection(section, report, options = {}) {
  if (!section.fields.length && !section.body_markdown) return "";
  return `
    <div class="report-section" data-section-id="${section.id}">
      ${sectionHeader(section)}
      <div class="${options.compact ? "form-grid compact-form" : "field-grid"}">
        ${section.fields.map((field) => {
          if (options.resultSpectrumLabels?.includes(field.label) || isResultField(field)) {
            return `<div class="full bold-result">${fieldQuestionLine(field)}${resultSpectrum(field, report)}</div>`;
          }
          return screeningFieldInput(field, report, {
            compact: options.compact,
            compactTextarea: options.compactTextareas,
            inheritedBadge: options.inheritedBadge,
          });
        }).join("")}
      </div>
    </div>
  `;
}

function compactMetadataSection(section, report, options = {}) {
  const tableEditor = options.tableEditor === true
    ? { compactTextarea: true }
    : { compactTextarea: true, ...(options.tableEditor || {}) };
  return `
    <div class="report-section" data-section-id="${section.id}">
      ${sectionHeader(section, options.headerOptions || {})}
      ${options.banner || ""}
      ${dataPointTable(section.fields, report, { tableEditor, hideFieldTools: options.hideFieldTools })}
    </div>
  `;
}

function basicInputsSection(section, report) {
  return compactMetadataSection(section, report, {
    headerOptions: { hideActions: true, hideNotes: true },
    hideFieldTools: true,
    tableEditor: { showTools: false },
  });
}

function sectionHeader(section, options = {}) {
  const key = `section:${section.id}`;
  const hasNote = Boolean((state.fieldNotes[key] || "").trim());
  return `
    <div class="section-heading">
      <div>
        <h3 class="section-title">${escapeHtml(section.title)}</h3>
        ${options.hideActions ? "" : `<div class="section-actions">
          <button type="button" class="inline-tool" data-source-field="${escapeAttr(key)}" data-field-label="${escapeAttr(`${section.title} section sources`)}">Section Sources ${fieldSourceCount(key)}</button>
          <button type="button" class="inline-tool" data-apply-section-sources="${escapeAttr(section.id)}">Apply to all answers</button>
        </div>`}
      </div>
      ${options.hideNotes ? "" : `<details class="section-notes">
        <summary class="${hasNote ? "has-note" : ""}">Notes</summary>
        <textarea rows="1" data-autosize-textarea="1" data-section-note="${escapeAttr(key)}">${escapeHtml(state.fieldNotes[key] || "")}</textarea>
      </details>`}
    </div>
  `;
}

function fastKillSection(section, report) {
  const questionFields = section.fields.filter((field) => field.kind === "select" && !isResultField(field));
  const result = section.fields.find((field) => field.label === "Fast Kill Result");
  const reason = section.fields.find((field) => field.label.startsWith("If Archive") || field.label.startsWith("If not"));
  return `
    <div class="report-section" data-section-id="${section.id}">
      ${sectionHeader(section)}
      ${questionMatrixTable(questionFields, report, { options: orderedQuestionMatrixOptions(questionFields), tableClass: "fast-kill-table" })}
      ${result ? `<div class="bold-result">${fieldQuestionLine(result)}${resultSpectrum(result, report)}</div>` : ""}
      ${reason ? screeningFieldInput(reason, report, { full: true }) : ""}
    </div>
  `;
}

function hardGateSection(section, report) {
  const questions = sectionFieldsByOrigin(section, "question");
  const ruleRows = hardGateRuleRows(section.body_markdown);
  const hardFails = bulletsAfterHeading(section.body_markdown, "Hard-fail items:");
  const result = section.fields.find(isResultField);
  const notes = section.fields.find((field) => field.label === "Notes");
  const otherFields = section.fields.filter((field) => field !== result && field !== notes && field.origin !== "question");
  return `
    <div class="report-section" data-section-id="${section.id}">
      ${sectionHeader(section, { hideNotes: true })}
      ${questions.length ? `
        ${questionDropdownTable(questions, report)}
      ` : ""}
      ${hardFails.length ? `
        <div class="source-guidance-box warning-box">
          <strong>Hard-fail items</strong>
          <ul>${hardFails.map((item) => `<li>${escapeHtml(stripInlineMarkdown(item))}</li>`).join("")}</ul>
        </div>
      ` : ""}
      ${ruleRows.length ? `
        <div class="table-wrap">
          <table class="decision-table guidance-table">
            <thead><tr><th>Option</th><th>Guidance from source</th></tr></thead>
            <tbody>
              ${ruleRows.map((row) => `
                <tr>
                  <td><span class="pill ${decisionClass(row.option)}">${escapeHtml(row.option)}</span></td>
                  <td>${escapeHtml(row.guidance)}</td>
                </tr>
              `).join("")}
            </tbody>
          </table>
        </div>
      ` : ""}
      ${otherFields.length ? `<div class="field-grid">${otherFields.map((field) => screeningFieldInput(field, report)).join("")}</div>` : ""}
      ${result ? `<div class="bold-result">${fieldQuestionLine(result)}${resultSpectrum(result, report)}</div>` : ""}
      ${notes ? collapsibleNotesField(notes, report) : ""}
    </div>
  `;
}

function groupedTableSection(section, report, columns, options = {}) {
  const groups = groupFieldsByRow(section.fields, columns);
  return `
    <div class="report-section" data-section-id="${section.id}">
      ${sectionHeader(section)}
      <div class="table-wrap">
        <table class="decision-table">
          <thead><tr><th>Item</th>${columns.map((column) => `<th>${escapeHtml(column)}</th>`).join("")}</tr></thead>
          <tbody>
            ${Object.entries(groups).map(([rowLabel, fields]) => `
              <tr ${reportRowAttrs(Object.values(fields), report)}>
                <td>${escapeHtml(rowLabel)}</td>
                ${columns.map((column) => `<td>${fields[column] ? groupedTableCell(fields[column], column, report, options) : ""}</td>`).join("")}
              </tr>
            `).join("")}
          </tbody>
        </table>
      </div>
    </div>
  `;
}

function groupFieldsByRow(fields, columns) {
  const groups = {};
  fields.forEach((field) => {
    const column = columns.find((item) => field.label.endsWith(`- ${item}`));
    if (!column) return;
    const row = field.label.slice(0, -(`- ${column}`).length).trim();
    groups[row] = groups[row] || {};
    groups[row][column] = field;
  });
  return groups;
}

function groupedTableCell(field, column, report, options = {}) {
  if (column.toLowerCase() === "source") return sourceButtonControl(field);
  const editorOptions = options.tableEditor === true ? {} : (options.tableEditor || {});
  return tableFieldEditor(field, report, editorOptions);
}

function hardGateSummarySection(section, report, schema) {
  const gateSections = schema.sections.filter((item) => isHardGateSection(item, schema));
  return `
    <div class="report-section" data-section-id="${section.id}">
      ${sectionHeader(section)}
      <div class="table-wrap">
        <table class="decision-table hard-gate-summary-table">
          <thead><tr><th>Gate</th><th>Result</th><th>Sources</th><th>Main Note</th></tr></thead>
          <tbody>
            ${gateSections.map((gate) => {
              const result = gate.fields.find(isResultField);
              const notes = gate.fields.find((field) => field.label === "Notes");
              return `
                <tr ${reportRowAttrs([result, notes], report)}>
                  <td><strong>${escapeHtml(gate.title.replace(/^\d+\.\s*/, ""))}</strong></td>
                  <td>${result ? readonlyResultPill(result, report) : ""}</td>
                  <td>${result ? sourceSnapshot(result.id) : ""}</td>
                  <td>${notes ? `<textarea rows="1" data-autosize-textarea="1" data-field-id="${escapeAttr(notes.id)}" data-field-kind="${escapeAttr(notes.kind)}">${escapeHtml(fieldValue(notes, report))}</textarea>` : ""}</td>
                </tr>
              `;
            }).join("")}
          </tbody>
        </table>
      </div>
    </div>
  `;
}

function readonlyResultPill(field, report) {
  const value = fieldValue(field, report);
  if (!value) return `<span class="muted">Not answered</span>`;
  return `<span class="pill ${decisionClass(value)}">${escapeHtml(value)}</span>`;
}

function sourceSnapshot(fieldId) {
  const entry = state.fieldSources[fieldId] || { source_ids: [], citation: "" };
  const selected = new Set((entry.source_ids || []).map(String));
  const sources = availableSources(state.currentReport).filter((source) => selected.has(String(source.id)));
  if (!sources.length && !entry.citation) return `<span class="muted">No sources linked</span>`;
  return `
    <div class="source-snapshot">
      ${sources.map((source) => `<span class="pill">${escapeHtml(source.title)}</span>`).join("")}
      ${entry.citation ? `<small>${escapeHtml(entry.citation)}</small>` : ""}
    </div>
  `;
}

function returnsMarginsSection(section, report) {
  const result = section.fields.find(isResultField);
  const fields = section.fields.filter((field) => !isResultField(field));
  return `
    <div class="report-section" data-section-id="${section.id}">
      ${sectionHeader(section)}
      ${dataPointTable(fields, report)}
      ${result ? `<div class="bold-result">${fieldQuestionLine(result)}${resultSpectrum(result, report)}</div>` : ""}
    </div>
  `;
}

function ownerSanitySection(section, report) {
  const worksheetFields = section.fields.filter((field) => !isResultField(field) && field.origin !== "question");
  const result = section.fields.find(isResultField);
  const questions = section.fields.filter((field) => field.origin === "question");
  return `
    <div class="report-section" data-section-id="${section.id}">
      ${sectionHeader(section)}
      ${dataPointTable(worksheetFields, report)}
      ${questionDropdownTable(questions, report)}
      ${result ? `<div class="bold-result">${fieldQuestionLine(result)}${resultSpectrum(result, report)}</div>` : ""}
    </div>
  `;
}

function perShareSection(section, report) {
  const worksheetFields = section.fields.filter((field) => !isResultField(field) && field.origin !== "question");
  const result = section.fields.find(isResultField);
  const questions = section.fields.filter((field) => field.origin === "question");
  return `
    <div class="report-section" data-section-id="${section.id}">
      ${sectionHeader(section)}
      ${questionDropdownTable(questions, report)}
      ${dataPointTable(worksheetFields, report)}
      ${result ? `<div class="bold-result">${fieldQuestionLine(result)}${resultSpectrum(result, report)}</div>` : ""}
    </div>
  `;
}

function questionDropdownTable(questions, report, options = {}) {
  if (!questions.length) return "";
  const sharedOptions = sharedQuestionOptions(questions);
  if (sharedOptions) {
    return questionMatrixTable(questions, report, {
      options: sharedOptions,
      tableClass: "question-dropdown-matrix-table",
    });
  }
  return `
    <div class="table-wrap">
      <table class="decision-table two-col-table">
        <thead><tr><th>Question</th><th>Response</th></tr></thead>
        <tbody>
          ${questions.map((field) => {
            const editorOptions = options.tableEditor === true ? {} : (options.tableEditor || {});
            const control = isAutoInheritedField(report, field.id)
              ? readonlyTableFieldEditor(field, report, editorOptions)
              : (options.tableEditor ? tableFieldEditor(field, report, editorOptions) : screeningFieldControl(field, report, { hideLabel: true }));
            return `<tr ${reportRowAttrs([field], report)}><td>${fieldQuestionLine(field)}</td><td>${control}</td></tr>`;
          }).join("")}
        </tbody>
      </table>
    </div>
  `;
}

function sharedQuestionOptions(questions) {
  if (!questions.length) return null;
  const optionSets = questions.map((field) => {
    if (field.kind !== "select") return null;
    const options = filteredOptions(field.options || []);
    if (options.length < 2 || options.length > 5) return null;
    return options;
  });
  if (optionSets.some((options) => !options)) return null;
  const signature = optionSets[0].join("\u0000");
  return optionSets.every((options) => options.join("\u0000") === signature) ? optionSets[0] : null;
}

function orderedQuestionMatrixOptions(questions) {
  const seen = new Set();
  const options = [];
  questions.forEach((field) => {
    filteredOptions(field.options || []).forEach((option) => {
      if (seen.has(option)) return;
      seen.add(option);
      options.push(option);
    });
  });
  return options;
}

function questionMatrixTable(questions, report, options = {}) {
  const matrixOptions = options.options || sharedQuestionOptions(questions);
  if (!questions.length || !matrixOptions?.length) return "";
  const tableClass = ["decision-table", "question-matrix-table", options.tableClass || ""].filter(Boolean).join(" ");
  return `
    <div class="table-wrap">
      <table class="${tableClass}">
        <thead><tr><th>Question</th>${matrixOptions.map((option) => `<th>${escapeHtml(option)}</th>`).join("")}</tr></thead>
        <tbody>
          ${questions.map((field) => `
            <tr ${reportRowAttrs([field], report)}>
              <td>${fieldQuestionLine(field)}</td>
              ${matrixOptions.map((option) => filteredOptions(field.options || []).includes(option)
                ? radioCell(field, option, report, { hideLabel: true })
                : "<td></td>").join("")}
            </tr>
          `).join("")}
        </tbody>
      </table>
    </div>
  `;
}

function dataPointTable(fields, report, options = {}) {
  if (!fields.length) return "";
  return `
    <div class="table-wrap">
      <table class="decision-table data-point-table">
        <thead><tr><th>Data point</th><th>Response</th></tr></thead>
        <tbody>
            ${fields.map((field) => `
            <tr ${reportRowAttrs([field], report)}>
              <td>${fieldQuestionLine(field, { hideTools: options.hideFieldTools })}</td>
              <td>${isAutoInheritedField(report, field.id)
                ? readonlyTableFieldEditor(field, report, options.tableEditor === true ? {} : (options.tableEditor || {}))
                : (options.tableEditor
                  ? tableFieldEditor(field, report, options.tableEditor === true ? {} : options.tableEditor)
                  : screeningFieldControl(field, report, { hideLabel: true, compact: true }))}</td>
            </tr>
          `).join("")}
        </tbody>
      </table>
    </div>
  `;
}

function sectionFieldsByOrigin(section, origin) {
  return (section.fields || []).filter((field) => field.origin === origin);
}

function balanceSheetSection(section, report) {
  const result = section.fields.find(isResultField);
  const fields = section.fields.filter((field) => !isResultField(field));
  return `
    <div class="report-section" data-section-id="${section.id}">
      ${sectionHeader(section)}
      ${dataPointTable(fields, report)}
      ${result ? `<div class="bold-result">${fieldQuestionLine(result)}${resultSpectrum(result, report)}</div>` : ""}
    </div>
  `;
}

function collapsibleNotesField(field, report) {
  const value = fieldValue(field, report);
  const hasValue = Boolean(String(value || "").trim());
  return `
    <details class="big-notes-field" ${reportFieldWrapperAttrs(field, report)} ${hasValue ? "open" : ""}>
      <summary class="${hasValue ? "has-note" : ""}">Notes</summary>
      <textarea rows="1" data-autosize-textarea="1" data-field-id="${escapeAttr(field.id)}" data-field-kind="${escapeAttr(field.kind)}">${escapeHtml(value)}</textarea>
    </details>
  `;
}

function readonlyTableFieldEditor(field, report, options = {}) {
  const badge = options.badge ? `<span class="muted inherited-tag">${escapeHtml(options.badge)}</span>` : "";
  const tools = options.showTools === false ? "" : `<div class="mini-field-tools">
        <button type="button" class="inline-tool" data-source-field="${escapeAttr(field.id)}" data-field-label="${escapeAttr(displayFieldLabel(field.label))}">Sources ${fieldSourceCount(field.id)}</button>
        <button type="button" class="inline-tool ${fieldHasNote(field.id) || fieldHasException(field.id) ? "has-note" : ""}" data-note-field="${escapeAttr(field.id)}" data-field-label="${escapeAttr(displayFieldLabel(field.label))}">${fieldNoteButtonLabel(field)}</button>
      </div>`;
  return `
    <div class="table-field-stack inherited-field" ${reportFieldWrapperAttrs(field, report)}>
      ${readonlyFieldControl(field, fieldValue(field, report))}
      ${badge || tools ? `<div class="table-field-meta">${badge}${tools}</div>` : ""}
    </div>
  `;
}

function tableFieldEditor(field, report, options = {}) {
  if (isAutoInheritedField(report, field.id)) {
    return readonlyTableFieldEditor(field, report, options);
  }
  return `
    <div class="table-field-stack" ${reportFieldWrapperAttrs(field, report)}>
      ${screeningFieldControl(field, report, { hideLabel: true, compact: true, compactTextarea: options.compactTextarea })}
      ${options.showTools === false ? "" : `<div class="mini-field-tools">
        <button type="button" class="inline-tool" data-source-field="${escapeAttr(field.id)}" data-field-label="${escapeAttr(displayFieldLabel(field.label))}">Sources ${fieldSourceCount(field.id)}</button>
        <button type="button" class="inline-tool ${fieldHasNote(field.id) || fieldHasException(field.id) ? "has-note" : ""}" data-note-field="${escapeAttr(field.id)}" data-field-label="${escapeAttr(displayFieldLabel(field.label))}">${fieldNoteButtonLabel(field)}</button>
      </div>`}
    </div>
  `;
}

function valuationSection(section, report) {
  const fields = section.title === "2. Simple Valuation Markers"
    ? section.fields.filter((field) => field.label !== "Notes")
    : section.fields;
  return standardScreeningSection({ ...section, fields }, report, { compact: true, compactTextareas: COMPACT_TEXTAREA_SECTIONS.has(section.title) });
}

function whatMustBeTrueSection(section, report) {
  const fragility = section.fields.find((field) => field.label === "Fragility Read");
  const rowNumbers = [...new Set((section.fields || []).map((field) => {
    const match = field.label.match(/^What must be true\?\s+(\d+)\s+-/i);
    return match ? Number(match[1]) : null;
  }).filter(Boolean))].sort((left, right) => left - right);
  return `
    <div class="report-section" data-section-id="${section.id}">
      ${sectionHeader(section)}
      <div class="table-wrap">
        <table class="decision-table">
          <thead><tr><th>What must be true?</th><th>Current evidence</th><th>Source</th><th>Confidence</th><th>Funnel stage to verify</th><th>How to verify</th></tr></thead>
          <tbody>
            ${rowNumbers.map((rowNumber) => whatMustBeTrueRow(section, report, rowNumber)).join("")}
          </tbody>
        </table>
      </div>
      ${fragility ? `<div class="bold-result">${fieldQuestionLine(fragility)}${resultSpectrum(fragility, report)}</div>` : ""}
    </div>
  `;
}

function whatMustBeTrueRow(section, report, rowNumber) {
  const prefix = `What must be true? ${rowNumber}`;
  const find = (suffix) => section.fields.find((field) => field.label === `${prefix} - ${suffix}`);
  const must = find("Thesis condition");
  const evidence = find("Current evidence");
  const source = find("Source");
  const confidence = find("Confidence");
  const stage = find("Funnel stage to verify");
  const how = find("How to verify");
  return `
    <tr ${reportRowAttrs([must, evidence, source, confidence, stage, how], report)}>
      <td>${must ? tableFieldEditor(must, report, { compactTextarea: true }) : ""}</td>
      <td>${evidence ? tableFieldEditor(evidence, report, { compactTextarea: true }) : ""}</td>
      <td>${source ? sourceButtonControl(source) : ""}</td>
      <td>${confidence ? tableFieldEditor(confidence, report) : ""}</td>
      <td>${stage ? tableFieldEditor(stage, report) : ""}</td>
      <td>${how ? tableFieldEditor(how, report, { compactTextarea: true }) : ""}</td>
    </tr>
  `;
}

function biasAuditSection(section, report) {
  const checks = section.fields.filter((field) => field.kind === "checkbox" || field.origin === "checkbox");
  const answerField = section.fields.find((field) => field.label === "Most important bias risk")
    || section.fields.find((field) => field.kind === "textarea" && field.origin !== "checkbox");
  return `
    <div class="report-section" data-section-id="${section.id}">
      ${sectionHeader(section)}
      <div class="checkbox-list">
        ${checks.map((field) => checkboxField(field, report)).join("")}
      </div>
      ${answerField ? screeningFieldInput(answerField, report, { full: true }) : ""}
    </div>
  `;
}

function businessCategorySection(section, report, schema) {
  const result = schema.fields.find((field) => field.label === "Business Category Result");
  const categories = [
    ["Exceptional Compounder", "Durable demand, evidenced moat, pricing power, high returns, conservative balance sheet, long runway.", "Can pass with a smaller apparent discount only if durability and reinvestment evidence are unusually strong."],
    ["Good Predictable", "Understandable economics, acceptable returns, some moat, stable margins, sound balance sheet.", "Needs a visible discount or a clear path to per-share value growth."],
    ["Cyclical-Commodity", "Earnings depend on commodity prices, macro cycles, capacity, rates, or asset values.", "Use normalized earnings, require a strong balance sheet and a large discount."],
    ["Financial-Insurer", "Value depends on underwriting, credit quality, capital, liquidity, reserves, and asset/liability match.", "Use a financial-specific underwriting process if needed."],
    ["Special Situation", "Catalyst, transaction, liquidation, spin-off, legal claim, restructuring, or event-driven return.", "Use a separate special-situation checklist."],
    ["Too Hard", "Opaque economics, too many moving parts, unknowable technology/regulation/financing/macro dependence.", "Archive."],
  ];
  return `
    <div class="report-section" data-section-id="${section.id}">
      ${sectionHeader(section)}
      <div class="table-wrap">
        <table class="category-table">
          <thead><tr><th>Category</th><th>Description</th><th>Screening Standard</th></tr></thead>
          <tbody>
            ${categories.map((row, index) => `
              <tr class="category-row-${index + 1}">
                <td><strong>${escapeHtml(row[0])}</strong></td>
                <td>${escapeHtml(row[1])}</td>
                <td>${escapeHtml(row[2])}</td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      </div>
      ${result ? `<div class="bold-result">${fieldQuestionLine(result)}${resultSpectrum(result, report)}</div>` : ""}
    </div>
  `;
}

function onePageConclusionSection(section, report, schema) {
  const basicValues = basicInputValues(report, schema);
  return `
    <div class="report-section" data-section-id="${section.id}">
      ${sectionHeader(section)}
      <div class="field-grid">
        ${section.fields.map((field) => {
          const derived = derivedConclusionValue(field, report, basicValues);
          if (derived !== null) {
            return readonlyReportField(field, derived);
          }
          if (isResultField(field)) {
            return `<div class="full bold-result">${fieldQuestionLine(field)}${resultSpectrum(field, report)}</div>`;
          }
          return screeningFieldInput(field, report, { compactTextarea: true });
        }).join("")}
      </div>
    </div>
  `;
}

function basicInputValues(report, schema) {
  const basic = schema.sections.find((section) => section.title === "Basic Inputs");
  const values = {};
  (basic?.fields || []).forEach((field) => {
    const value = fieldValue(field, report);
    if (value) values[field.label.toLowerCase()] = value;
  });
  values.company = values.company || report.company_name || "";
  values.ticker = values.ticker || report.ticker || "";
  return values;
}

function derivedConclusionValue(field, report, basicValues) {
  const label = field.label.toLowerCase();
  if (label === "company / ticker") {
    const company = basicValues.company || report.company_name || "";
    const ticker = basicValues.ticker || report.ticker || "";
    return [company, ticker].filter(Boolean).join(" / ");
  }
  if (Object.prototype.hasOwnProperty.call(basicValues, label)) return basicValues[label];
  return null;
}

function screeningDecisionPanel(report) {
  const schema = report.template.schema || { sections: [] };
  const pass = schema.sections.find((section) => section.title === "If It Passes Screening");
  const watch = schema.sections.find((section) => section.title === "If It Goes To Watchlist");
  const archive = schema.sections.find((section) => section.title === "If It Is Archived");
  const decisionDescriptions = decisionDescriptionsFromCoreRules(schema);
  const selectedDecision = finalDecisionFromReport(report, schema);
  return `
    <section class="panel">
      <div class="panel-header">
        <div>
          <h3>Decision Output</h3>
          <p class="muted">Choose one final screening destination. Only that destination remains editable.</p>
        </div>
      </div>
      <div class="panel-body grid decision-accordion">
        ${finalDecisionSpectrum(selectedDecision, schema)}
        ${pass ? destinationPanel(pass, report, "Pass", "Pass", passPanelContent(pass, report), selectedDecision === "Pass", decisionDescriptions.Pass) : ""}
        ${watch ? destinationPanel(watch, report, "Watchlist", "Watchlist", watchlistPanelContent(watch, report), selectedDecision === "Watchlist", decisionDescriptions.Watchlist) : ""}
        ${archive ? destinationPanel(archive, report, "Archive", "Archive", decisionPanelContent(archive, report), selectedDecision === "Archive", decisionDescriptions.Archive) : ""}
        <div class="button-row">
          ${reportSubmitButtons(report, { includeBack: true })}
        </div>
      </div>
    </section>
  `;
}

function finalDecisionOptions(schema) {
  const field = finalDecisionField(schema || { sections: [] });
  const rawOptions = filteredOptions(field?.options?.length ? field.options : DEFAULT_FINAL_DECISIONS.map(([label]) => label));
  const seen = new Set();
  const mapped = rawOptions.map((option) => [normalizeFinalDecision(option) || option, resultValueForDecisionOption(option)])
    .filter(([label]) => label)
    .filter(([label]) => {
      if (seen.has(label)) return false;
      seen.add(label);
      return true;
    });
  return mapped.length ? mapped : DEFAULT_FINAL_DECISIONS;
}

function finalDecisionSpectrum(selectedDecision, schema) {
  const options = finalDecisionOptions(schema);
  return `
    <div class="final-decision-box linked-final-decision">
      <strong>Final Decision</strong>
      <p class="muted">Locked to the Decision spectrum in the Final Decision subsection.</p>
      <div class="result-spectrum final-decision-spectrum" data-spectrum-options="${options.length}">
        ${options.map(([label, resultValue]) => {
          const checked = selectedDecision === label ? "checked" : "";
          return `<label><input type="radio" name="final_decision_display" data-linked-final-decision="${escapeAttr(label)}" data-result-value="${escapeAttr(resultValue)}" value="${escapeAttr(label)}" ${checked} disabled /><span class="tone-${spectrumTone(label)}">${escapeHtml(label)}</span></label>`;
        }).join("")}
      </div>
    </div>
  `;
}

function destinationPanel(section, report, title, decisionKey, body, open, description = "") {
  return `
    <details class="destination-panel" data-decision-panel="${escapeAttr(decisionKey)}" ${open ? "open" : ""}>
      <summary>${escapeHtml(title)}</summary>
      <div class="destination-body">
        ${description ? `<p class="muted decision-description">${escapeHtml(description)}</p>` : ""}
        ${body}
      </div>
    </details>
  `;
}

function decisionDescriptionsFromCoreRules(schema) {
  const coreRules = schema.sections.find((section) => section.title === "Core Rules");
  return (coreRules?.body_markdown || "").split("\n").reduce((acc, line) => {
    const match = line.trim().match(/^-\s+\*\*([^*]+)\*\*\s+means\s+"(.+?)"/i);
    if (match) acc[normalizeFinalDecision(match[1]) || match[1]] = match[3];
    return acc;
  }, {});
}

function finalDecisionFromResult(result, schema) {
  const match = finalDecisionOptions(schema).find(([, value]) => value === result);
  if (!match && /^Return to /i.test(String(result || ""))) {
    const genericReturn = finalDecisionOptions(schema).find(([label]) => label === "Return To Underwriting");
    if (genericReturn) return genericReturn[0];
  }
  return match ? match[0] : "";
}

function finalDecisionFromReport(report, schema) {
  const field = finalDecisionField(schema);
  const decision = field ? normalizeFinalDecision(fieldValue(field, report)) : "";
  return decision || finalDecisionFromResult(report.result, schema);
}

function finalDecisionField(schema) {
  const section = schema.sections.find((item) => item.title === "Final Decision");
  return section?.fields.find((field) => field.label === "Decision") || null;
}

function normalizeFinalDecision(value) {
  const text = String(value || "").toLowerCase();
  if (text.includes("return to business underwriting")) return "Return to Business Underwriting";
  if (text.includes("return to management underwriting")) return "Return to Management Underwriting";
  if (text.includes("return to financial underwriting")) return "Return to Financial Underwriting";
  if (text.includes("return to valuation and position size")) return "Return to Valuation and Position Size";
  if (text.includes("return to underwriting")) return "Return To Underwriting";
  if (text.includes("execute starter now")) return "Execute Starter Now";
  if (text.includes("enter staged orders")) return "Enter Staged Orders";
  if (text.includes("hold existing")) return "Hold Existing";
  if (text === "trim" || text.startsWith("trim ")) return "Trim";
  if (text === "exit" || text.startsWith("exit ")) return "Exit";
  if (text.includes("approve")) return "Approve For Execution";
  if (text.includes("pass") || text.includes("proceed")) return "Pass";
  if (text.includes("watchlist")) return "Watchlist";
  if (text.includes("archive")) return "Archive";
  return "";
}

function resultValueForDecisionOption(option) {
  const decision = normalizeFinalDecision(option) || String(option || "");
  if (["Execute Starter Now", "Enter Staged Orders", "Hold Existing", "Trim", "Exit"].includes(decision)) {
    return "Proceed to Next Step";
  }
  if (decision === "Approve For Execution") return "Proceed to Next Step";
  if (decision === "Pass") return "Proceed to Next Step";
  if (decision === "Watchlist") return "Watchlist";
  if (decision === "Archive") return "Archive";
  if (decision === "Return to Business Underwriting") return "Return to Business Underwriting";
  if (decision === "Return to Management Underwriting") return "Return to Management Underwriting";
  if (decision === "Return to Financial Underwriting") return "Return to Financial Underwriting";
  if (decision === "Return to Valuation and Position Size") return "Return to Valuation and Position Size";
  return "";
}

function resultValueForFinalDecision(decision) {
  return resultValueForDecisionOption(decision);
}

function passPanelContent(section, report) {
  const requirements = bulletsAfterHeading(section.body_markdown, "Pass Screening requires:");
  const handoff = section.fields.filter((field) => field.label.startsWith("Business Underwriting handoff "));
  const downstream = section.fields.filter((field) => !field.label.startsWith("Business Underwriting handoff "));
  return `
    <div class="handoff-preview">
      <strong>Business Underwriting Handoff</strong>
      <p class="muted">Preserve the most important unresolved issues instead of solving them in Screening.</p>
    </div>
    ${requirements.length ? `
      <div class="source-guidance-box">
        <strong>Pass Screening requires</strong>
        <ul>${requirements.map((item) => `<li>${escapeHtml(stripInlineMarkdown(item))}</li>`).join("")}</ul>
      </div>
    ` : ""}
    ${passIssueExplanation()}
    <div class="field-grid">
      ${handoff.map((field) => screeningFieldInput(field, report, { full: true })).join("")}
      ${downstream.map((field) => screeningFieldInput(field, report, { compact: true })).join("")}
    </div>
  `;
}

function passIssueExplanation() {
  const issues = [
    ["Management Underwriting issue", "Preserve unresolved management, incentives, capital allocation, compensation, acquisition, or disclosure questions."],
    ["Financial Underwriting issue", "Preserve unresolved balance-sheet, accounting, cash conversion, leverage, liquidity, or owner-earnings questions."],
    ["Valuation and Position Size issue", "Preserve unresolved normalized economics, valuation range, margin-of-safety, or position-sizing questions."],
    ["Execution Rules issue", "Preserve unresolved buying rules, sell rules, monitoring triggers, or execution constraints."],
  ];
  return `
    <div class="source-guidance-box">
      <strong>Downstream Issues To Preserve</strong>
      <p class="muted">From the source questionnaire: preserve, but do not solve yet, the key downstream issues for later underwriting stages.</p>
      <div class="table-wrap">
        <table class="decision-table two-col-table">
          <thead><tr><th>Issue</th><th>What to capture</th></tr></thead>
          <tbody>
            ${issues.map(([label, description]) => `<tr><td>${escapeHtml(label)}</td><td>${escapeHtml(description)}</td></tr>`).join("")}
          </tbody>
        </table>
      </div>
    </div>
  `;
}

function watchlistPanelContent(section, report) {
  const descriptions = bulletLabelDescriptions(section.body_markdown);
  return `
    <div class="source-guidance-box">
      <strong>Watchlist Instructions</strong>
      <p class="muted">Choose the main reasons this company belongs on the watchlist and explain the condition or evidence needed before reviewing it again.</p>
    </div>
    <div class="table-wrap">
      <table class="decision-table two-col-table">
        <thead><tr><th>Watchlist Label</th><th>Trigger / Answer</th></tr></thead>
        <tbody>
          ${section.fields.map((field) => `
            <tr>
              <td><strong>${escapeHtml(field.label)}</strong><br><span class="muted">${escapeHtml(descriptions[field.label] || "")}</span></td>
              <td>${tableFieldEditor(field, report, { compactTextarea: true })}</td>
            </tr>
          `).join("")}
        </tbody>
      </table>
    </div>
    ${decisionReviewControl(report, "Watchlist")}
  `;
}

function decisionPanelContent(section, report) {
  return `
    ${decisionSourceDescription(section)}
    ${standardPanelFields(section, report)}
    ${section.title === "If It Is Archived" ? decisionReviewControl(report, "Archive") : ""}
  `;
}

function decisionReviewControl(report, decision) {
  const value = report.review_date || "";
  const intervalMode = /^in\s+/i.test(value) || /\b(month|months|week|weeks|year|years|day|days)\b/i.test(value);
  return `
    <div class="decision-review-control" data-review-control="${escapeAttr(decision)}">
      <strong>Suggested Next Review</strong>
      <div class="form-grid compact-form">
        <label>Type
          <select data-review-mode>
            <option value="date" ${intervalMode ? "" : "selected"}>Specific date</option>
            <option value="interval" ${intervalMode ? "selected" : ""}>Time span</option>
          </select>
        </label>
        <label>Testing date or interval
          <input data-review-value value="${escapeAttr(value)}" placeholder="2026-05-16 or in 1 month" />
        </label>
      </div>
    </div>
  `;
}

function decisionSourceDescription(section) {
  const descriptions = bulletLabelDescriptions(section.body_markdown);
  if (!Object.keys(descriptions).length) return "";
  return `
    <div class="source-guidance-box">
      <strong>Descriptions from source</strong>
      <div class="table-wrap">
        <table class="decision-table two-col-table">
          <thead><tr><th>Field</th><th>Description</th></tr></thead>
          <tbody>
            ${Object.entries(descriptions).map(([label, description]) => `
              <tr><td>${escapeHtml(label)}</td><td>${escapeHtml(description)}</td></tr>
            `).join("")}
          </tbody>
        </table>
      </div>
    </div>
  `;
}

function bulletLabelDescriptions(markdown) {
  return (markdown || "").split("\n").reduce((acc, line) => {
    const trimmed = line.trim();
    const match = trimmed.match(/^-\s+(?:\*\*)?(.+?)(?:\*\*)?:\s*(.+?)\s*:?$/);
    if (match) acc[stripInlineMarkdown(match[1])] = stripInlineMarkdown(match[2]);
    return acc;
  }, {});
}

function standardPanelFields(section, report) {
  return `<div class="field-grid">${section.fields.map((field) => screeningFieldInput(field, report, { compact: true })).join("")}</div>`;
}

function isBusinessUnderwritingReport(report) {
  return report.template?.stage_key === "business_underwriting" || report.stage_name === "Business Underwriting";
}

function isManagementUnderwritingReport(report) {
  return report.template?.stage_key === "management_underwriting" || report.stage_name === "Management Underwriting";
}

function isFinancialUnderwritingReport(report) {
  return report.template?.stage_key === "financial_underwriting" || report.stage_name === "Financial Underwriting";
}

function isValuationPositionSizeReport(report) {
  return report.template?.stage_key === "valuation_position_size" || report.stage_name === "Valuation and Position Size";
}

function isExecutionRulesReport(report) {
  return report.template?.stage_key === "execution_rules" || report.stage_name === "Execution Rules";
}

function renderBusinessUnderwritingReportEditor(report) {
  const template = report.template;
  const schema = template.schema || { sections: [], fields: [] };
  const sections = schema.sections.filter((section) => !skipBusinessUnderwritingSection(section));
  const selectedFinalDecision = finalDecisionFromReport(report, schema);
  content.innerHTML = `
    <form id="report-form" class="grid screening-report underwriting-report">
      <section class="panel">
        <div class="panel-header detail-head">
          <div>
            <button class="secondary" type="button" data-company-return="${report.company_id}">Back to Company</button>
            <p class="eyebrow">${escapeHtml(report.stage_name)}</p>
            <h3 class="company-title">${escapeHtml(report.title)}</h3>
            <p class="muted">Business underwriting questionnaire. Sources, notes, and evidence links stay aligned with the Screening report workflow.</p>
          </div>
          <div class="button-row">
            <button class="danger" type="button" data-delete-report="${report.id}" data-company-id="${report.company_id}" data-report-title="${escapeAttr(report.title)}">Delete Report</button>
            ${reportSubmitButtons(report)}
          </div>
        </div>
        <div class="panel-body form-grid compact-form">
          <label>Title <input name="title" value="${escapeAttr(report.title)}" /></label>
          <label>Report month <input name="report_month" value="${escapeAttr(report.report_month || "")}" /></label>
          <input type="hidden" name="result" value="${escapeAttr(resultValueForFinalDecision(selectedFinalDecision) || report.result || "Draft")}" />
          <input type="hidden" name="review_date" value="${escapeAttr(report.review_date || "")}" />
        </div>
        ${reportQualityBanner(report)}
      </section>

      ${screeningSourcesPanel(report)}

      <section class="panel">
        <div class="panel-body">
          ${sections.map((section) => businessUnderwritingSection(section, report, schema)).join("")}
        </div>
      </section>

      ${businessUnderwritingDecisionPanel(report)}
    </form>
    ${fieldPopoverMarkup()}
    ${sourceDialogMarkup(report)}
    ${sourceDeleteDialogMarkup()}
    ${documentPreviewDialogMarkup()}
  `;
  initializeAnswerableReportSections(report, schema);
  bindScreeningReportEvents(report);
}

function skipBusinessUnderwritingSection(section) {
  const title = section.title || "";
  if (title.startsWith("Stock Candidate Business Underwriting Questionnaire")) return true;
  if (title === "Core Rules") return true;
  if (["If It Passes Business Underwriting", "If It Goes To Watchlist", "If It Is Archived"].includes(title)) return true;
  return !(section.fields || []).length;
}

function businessUnderwritingSection(section, report, schema) {
  if (section.title === "Basic Inputs") {
    return basicInputsSection(section, report);
  }
  if (section.title === "Inherited From Screening") {
    return businessInheritedScreeningSection(section, report);
  }
  if (section.title === "1. Evidence Coverage Check") {
    return businessQuestionSection(section, report);
  }
  if (section.title === "2. Evidence Log") {
    return businessEvidenceLogSection(section, report);
  }
  if (section.title === "3. Evidence Read") {
    return standardScreeningSection(section, report, { compactTextareas: true, resultSpectrumLabels: ["Evidence Result"] });
  }
  if (["1. Supply Advantage", "2. Demand Advantage / Customer Captivity", "3. Scale Advantage", "4. Local Dominance, Partial Monopoly, And Regulation"].includes(section.title)) {
    return businessAdvantageSection(section, report);
  }
  if (section.title === "5. Overall Advantage Conclusion") {
    return businessMixedSection(section, report, { dataFirst: true });
  }
  if (section.title === "Part V. Franchise, Commodity, And Pricing Power Test") {
    return standardScreeningSection(section, report, { compactTextareas: true, resultSpectrumLabels: ["Business Type Result"] });
  }
  if (["1. Core Operating Statistics", "2. Unit Economics", "Part VII. Economic Goodwill, Capital Intensity, And Inflation Test", "Part VIII. Reinvestment Runway And Growth Quality", "Part IX. Capital Cycle And Industry Evolution"].includes(section.title)) {
    return businessMixedSection(section, report);
  }
  if (section.title === "Part X. Competitive Destruction And Disconfirming Evidence") {
    return standardScreeningSection(section, report, { compactTextareas: true, resultSpectrumLabels: ["Failure-Mode Result"] });
  }
  if (section.title === "Part XI. What Must Be True / What To Verify") {
    return businessWhatMustBeTrueSection(section, report);
  }
  if (section.title === "Hard Gate Summary") {
    return groupedTableSection(section, report, ["Result", "Main Note"], { tableEditor: { compactTextarea: true } });
  }
  if (section.title === "Business Quality Summary") {
    return groupedTableSection(section, report, ["Rating", "Confidence"], { tableEditor: true });
  }
  if (section.title === "Final Decision") {
    return standardScreeningSection(section, report, { compact: true, compactTextareas: true, resultSpectrumLabels: ["Decision"] });
  }
  if (section.title === "One-Page Business Underwriting Conclusion") {
    return businessConclusionSection(section, report, schema);
  }
  return standardScreeningSection(section, report, { compactTextareas: true });
}

function businessInheritedScreeningSection(section, report) {
  const screening = report.inherited_screening;
  const banner = screening ? `
    <div class="source-guidance-box">
      <strong>Inherited From Latest Completed Screening Report</strong>
      <p class="muted">${escapeHtml(screening.title || "Screening report")}${screening.result ? ` • ${escapeHtml(screening.result)}` : ""}</p>
    </div>
  ` : "";
  return compactMetadataSection(section, report, {
    banner,
    tableEditor: { badge: "Pulled from Screening" },
  });
}

function inheritedReadonlyField(field, report, options = {}) {
  return readonlyReportField(field, fieldValue(field, report), {
    badge: options.inheritedBadge || "Read-only handoff",
    full: options.full,
    readonlyClass: "inherited-field",
  });
}

function fieldToolButtons(field, label = displayFieldLabel(field.label)) {
  return `
    <button type="button" class="inline-tool" data-source-field="${escapeAttr(field.id)}" data-field-label="${escapeAttr(label)}">Sources ${fieldSourceCount(field.id)}</button>
    <button type="button" class="inline-tool ${fieldHasNote(field.id) || fieldHasException(field.id) ? "has-note" : ""}" data-note-field="${escapeAttr(field.id)}" data-field-label="${escapeAttr(label)}">${fieldNoteButtonLabel(field)}</button>
  `;
}

function readonlyFieldControl(field, value) {
  if (field.kind === "textarea") {
    return `<textarea rows="1" data-autosize-textarea="1" readonly aria-readonly="true">${escapeHtml(value)}</textarea>`;
  }
  if (field.kind === "checkbox") {
    const checked = value === "true" || value === true ? "checked" : "";
    return `<input type="checkbox" disabled ${checked} aria-readonly="true" />`;
  }
  if (field.kind === "date") {
    return `<input type="date" value="${escapeAttr(value)}" readonly aria-readonly="true" />`;
  }
  return `<input value="${escapeAttr(value)}" readonly aria-readonly="true" />`;
}

function readonlyFieldQuestionLine(field, options = {}) {
  const label = displayFieldLabel(field.label);
  const badge = options.badge ? `<span class="muted inherited-tag">${escapeHtml(options.badge)}</span>` : "";
  return `
    <span class="question-line">
      <span>${escapeHtml(label)}${badge ? ` ${badge}` : ""}</span>
      <span class="field-tools">${fieldToolButtons(field, label)}</span>
    </span>
  `;
}

function readonlyReportField(field, value, options = {}) {
  const full = options.full || field.kind === "textarea" ? "full" : "";
  const classes = ["readonly-field", options.readonlyClass, full].filter(Boolean).join(" ");
  const filled = field.kind === "checkbox" ? value === true || value === "true" : Boolean(String(value || "").trim());
  return `
    <label class="${classes}" data-report-field-for="${escapeAttr(field.id)}" data-field-filled="${filled ? "1" : "0"}">
      ${readonlyFieldQuestionLine(field, options)}
      ${readonlyFieldControl(field, value)}
    </label>
  `;
}

function isAutoInheritedField(report, fieldId) {
  return (report.auto_inherited_fields || []).includes(fieldId);
}

function businessQuestionSection(section, report) {
  return `
    <div class="report-section" data-section-id="${section.id}">
      ${sectionHeader(section)}
      ${questionDropdownTable(section.fields, report, { tableEditor: { showTools: false } })}
    </div>
  `;
}

function businessMixedSection(section, report, options = {}) {
  const result = section.fields.find(isResultField);
  const questions = section.fields.filter((field) => field.origin === "question");
  const otherFields = section.fields.filter((field) => field !== result && field.origin !== "question");
  const first = options.dataFirst === false
    ? questionDropdownTable(questions, report, { tableEditor: { showTools: false } })
    : dataPointTable(otherFields, report, { tableEditor: { compactTextarea: true, showTools: false } });
  const second = options.dataFirst === false
    ? dataPointTable(otherFields, report, { tableEditor: { compactTextarea: true, showTools: false } })
    : questionDropdownTable(questions, report, { tableEditor: { showTools: false } });
  return `
    <div class="report-section" data-section-id="${section.id}">
      ${sectionHeader(section)}
      ${first}
      ${second}
      ${result ? `<div class="bold-result">${fieldQuestionLine(result)}${resultSpectrum(result, report)}</div>` : ""}
    </div>
  `;
}

function groupRepeatedTableFields(fields, columns) {
  const rows = [];
  let current = null;
  fields.forEach((field) => {
    const column = columns.find((item) => field.label.endsWith(` - ${item}`));
    if (!column) return;
    const rowLabel = field.label.slice(0, -(` - ${column}`).length).trim();
    const isFirstColumn = column === columns[0];
    if (!current || isFirstColumn || current.__rowLabel !== rowLabel || current[column]) {
      current = { __rowLabel: rowLabel };
      rows.push(current);
    }
    current[column] = field;
  });
  return rows;
}

function businessEvidenceLogSection(section, report) {
  const columns = ["Person / source", "Business question tested", "What it said", "Supports / Weakens / Mixed", "Evidence Grade", "Confidence"];
  const rows = groupRepeatedTableFields(section.fields, columns);
  return `
    <div class="report-section" data-section-id="${section.id}">
      ${sectionHeader(section)}
      <div class="table-wrap">
        <table class="decision-table source-log-table">
          <thead><tr><th>Source type</th>${columns.map((column) => `<th>${escapeHtml(column)}</th>`).join("")}</tr></thead>
          <tbody>
            ${rows.map((row) => `
              <tr ${reportRowAttrs(columns.map((column) => row[column]).filter(Boolean), report)}>
                <td><strong>${escapeHtml(row.__rowLabel)}</strong></td>
                ${columns.map((column) => `<td>${row[column] ? tableFieldEditor(row[column], report, { compactTextarea: true }) : ""}</td>`).join("")}
              </tr>
            `).join("")}
          </tbody>
        </table>
      </div>
    </div>
  `;
}

function businessAdvantageSection(section, report) {
  const questions = sectionFieldsByOrigin(section, "question");
  const ruleRows = hardGateRuleRows(section.body_markdown);
  const result = section.fields.find(isResultField);
  const notes = section.fields.find((field) => field.label === "Notes");
  const otherFields = section.fields.filter((field) => field !== result && field !== notes && field.origin !== "question");
  return `
    <div class="report-section" data-section-id="${section.id}">
      ${sectionHeader(section, { hideNotes: true })}
      ${questions.length ? questionDropdownTable(questions, report, { tableEditor: { showTools: false } }) : ""}
      ${ruleRows.length ? `
        <div class="table-wrap">
          <table class="decision-table guidance-table">
            <thead><tr><th>Option</th><th>Guidance from source</th></tr></thead>
            <tbody>
              ${ruleRows.map((row) => `
                <tr>
                  <td><span class="pill ${decisionClass(row.option)}">${escapeHtml(row.option)}</span></td>
                  <td>${escapeHtml(row.guidance)}</td>
                </tr>
              `).join("")}
            </tbody>
          </table>
        </div>
      ` : ""}
      ${otherFields.length ? dataPointTable(otherFields, report, { tableEditor: { compactTextarea: true, showTools: false } }) : ""}
      ${result ? `<div class="bold-result">${fieldQuestionLine(result)}${resultSpectrum(result, report)}</div>` : ""}
      ${notes ? collapsibleNotesField(notes, report) : ""}
    </div>
  `;
}

function businessWhatMustBeTrueSection(section, report) {
  const result = section.fields.find((field) => field.label === "Fragility Read");
  const rows = groupRepeatedTableFields(
    section.fields.filter((field) => field !== result),
    ["Thesis condition", "Why it matters", "Current evidence", "Gap or disconfirming evidence", "How to prove or disprove", "Best stage to finish verifying"],
  );
  return `
    <div class="report-section" data-section-id="${section.id}">
      ${sectionHeader(section)}
      <div class="table-wrap">
        <table class="decision-table">
          <thead><tr><th>Business claim that must be true</th><th>Why it matters</th><th>Current evidence</th><th>Gap or disconfirming evidence</th><th>How to prove or disprove</th><th>Best stage to finish verifying</th></tr></thead>
          <tbody>
            ${rows.map((row) => `
              <tr ${reportRowAttrs(Object.values(row).filter(Boolean), report)}>
                <td>${row["Thesis condition"] ? tableFieldEditor(row["Thesis condition"], report, { compactTextarea: true }) : ""}</td>
                <td>${row["Why it matters"] ? tableFieldEditor(row["Why it matters"], report, { compactTextarea: true }) : ""}</td>
                <td>${row["Current evidence"] ? tableFieldEditor(row["Current evidence"], report) : ""}</td>
                <td>${row["Gap or disconfirming evidence"] ? tableFieldEditor(row["Gap or disconfirming evidence"], report, { compactTextarea: true }) : ""}</td>
                <td>${row["How to prove or disprove"] ? tableFieldEditor(row["How to prove or disprove"], report, { compactTextarea: true }) : ""}</td>
                <td>${row["Best stage to finish verifying"] ? tableFieldEditor(row["Best stage to finish verifying"], report) : ""}</td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      </div>
      ${result ? `<div class="bold-result">${fieldQuestionLine(result)}${resultSpectrum(result, report)}</div>` : ""}
    </div>
  `;
}

function businessConclusionSection(section, report, schema) {
  return `
    <div class="report-section" data-section-id="${section.id}">
      ${sectionHeader(section)}
      <div class="field-grid">
        ${section.fields.map((field) => {
          const derived = businessConclusionValue(field, report, schema);
          if (derived !== null) {
            return readonlyReportField(field, derived);
          }
          if (isResultField(field)) {
            return `<div class="full bold-result">${fieldQuestionLine(field)}${resultSpectrum(field, report)}</div>`;
          }
          return screeningFieldInput(field, report, { compactTextarea: true });
        }).join("")}
      </div>
    </div>
  `;
}

function businessConclusionValue(field, report, schema) {
  const label = String(field.label || "").toLowerCase();
  const value = (sectionTitle, fieldLabel) => schemaFieldValue(report, schema, sectionTitle, fieldLabel);
  const inheritedCompany = value("Inherited From Screening", "Company") || report.company_name || "";
  const inheritedTicker = value("Inherited From Screening", "Ticker") || report.ticker || "";
  if (label === "company / ticker") return [inheritedCompany, inheritedTicker].filter(Boolean).join(" / ");
  if (label === "date") return value("Inherited From Screening", "Date");
  if (label === "decision") return value("Final Decision", "Decision");
  if (label === "business type") return value("Final Decision", "Business type");
  if (label === "next funnel stage") return value("Final Decision", "Next funnel stage");
  if (label === "screening claim tested") return value("Part I. Screening Handoff And Delta Thesis", "Which exact business claim from Screening is being tested now?");
  if (label === "market boundary") return value("1. Market Boundary", "What exact product or service market is being underwritten?");
  if (label === "primary source of advantage") return value("5. Overall Advantage Conclusion", "Primary source of advantage");
  return null;
}

function schemaFieldValue(report, schema, sectionTitle, fieldLabel) {
  const section = (schema.sections || []).find((item) => item.title === sectionTitle);
  const field = (section?.fields || []).find((item) => item.label === fieldLabel);
  return field ? fieldValue(field, report) : "";
}

function businessUnderwritingDecisionPanel(report) {
  const schema = report.template.schema || { sections: [] };
  const pass = schema.sections.find((section) => section.title === "If It Passes Business Underwriting");
  const watch = schema.sections.find((section) => section.title === "If It Goes To Watchlist");
  const archive = schema.sections.find((section) => section.title === "If It Is Archived");
  const decisionDescriptions = decisionDescriptionsFromCoreRules(schema);
  const selectedDecision = finalDecisionFromReport(report, schema);
  return `
    <section class="panel">
      <div class="panel-header">
        <div>
          <h3>Decision Output</h3>
          <p class="muted">Choose one business-underwriting destination. Only that destination remains editable.</p>
        </div>
      </div>
      <div class="panel-body grid decision-accordion">
        ${finalDecisionSpectrum(selectedDecision, schema)}
        ${pass ? destinationPanel(pass, report, "Pass Business Underwriting", "Pass", businessPassPanelContent(pass, report), selectedDecision === "Pass", decisionDescriptions.Pass) : ""}
        ${watch ? destinationPanel(watch, report, "Watchlist", "Watchlist", watchlistPanelContent(watch, report), selectedDecision === "Watchlist", decisionDescriptions.Watchlist) : ""}
        ${archive ? destinationPanel(archive, report, "Archive", "Archive", decisionPanelContent(archive, report), selectedDecision === "Archive", decisionDescriptions.Archive) : ""}
        <div class="button-row">
          ${reportSubmitButtons(report, { includeBack: true })}
        </div>
      </div>
    </section>
  `;
}

function renderManagementUnderwritingReportEditor(report) {
  const template = report.template;
  const schema = template.schema || { sections: [], fields: [] };
  const sections = schema.sections.filter((section) => !skipManagementUnderwritingSection(section));
  const selectedFinalDecision = finalDecisionFromReport(report, schema);
  content.innerHTML = `
    <form id="report-form" class="grid screening-report underwriting-report">
      <section class="panel">
        <div class="panel-header detail-head">
          <div>
            <button class="secondary" type="button" data-company-return="${report.company_id}">Back to Company</button>
            <p class="eyebrow">${escapeHtml(report.stage_name)}</p>
            <h3 class="company-title">${escapeHtml(report.title)}</h3>
            <p class="muted">Management underwriting questionnaire. Sources, notes, and citations stay aligned with the Screening and Business Underwriting workflow.</p>
          </div>
          <div class="button-row">
            <button class="danger" type="button" data-delete-report="${report.id}" data-company-id="${report.company_id}" data-report-title="${escapeAttr(report.title)}">Delete Report</button>
            ${reportSubmitButtons(report)}
          </div>
        </div>
        <div class="panel-body form-grid compact-form">
          <label>Title <input name="title" value="${escapeAttr(report.title)}" /></label>
          <label>Report month <input name="report_month" value="${escapeAttr(report.report_month || "")}" /></label>
          <input type="hidden" name="result" value="${escapeAttr(resultValueForFinalDecision(selectedFinalDecision) || report.result || "Draft")}" />
          <input type="hidden" name="review_date" value="${escapeAttr(report.review_date || "")}" />
        </div>
        ${reportQualityBanner(report)}
      </section>

      ${screeningSourcesPanel(report)}

      <section class="panel">
        <div class="panel-body">
          ${sections.map((section) => managementUnderwritingSection(section, report, schema)).join("")}
        </div>
      </section>

      ${managementUnderwritingDecisionPanel(report)}
    </form>
    ${fieldPopoverMarkup()}
    ${sourceDialogMarkup(report)}
    ${sourceDeleteDialogMarkup()}
    ${documentPreviewDialogMarkup()}
  `;
  initializeAnswerableReportSections(report, schema);
  bindScreeningReportEvents(report);
}

function skipManagementUnderwritingSection(section) {
  const title = section.title || "";
  if (title.startsWith("Stock Candidate Management Underwriting Questionnaire")) return true;
  if ([
    "Core Rules",
    "Evidence, Sources, And Confidence",
    "Part III. External Management Evidence And Interaction Log",
    "Part IV. Hard Management Gates",
    "Part VI. Capital Allocation Case File",
    "Part VII. Incentives, Governance, And Culture",
    "Part IX. Munger Error-Prevention Checks",
    "Part X. Management Category And Next Underwriting Standard",
    "Category Options",
    "Exceptional Owner-Operators",
    "Rational Stewards",
    "Capable But Agency-Risky",
    "Promotional / Empire-Building",
    "Control / Governance Risk",
    "If It Passes Management Underwriting",
    "If It Goes To Watchlist",
    "If It Is Archived",
  ].includes(title)) return true;
  return !(section.fields || []).length;
}

function managementUnderwritingSection(section, report, schema) {
  if (section.title === "Basic Inputs") {
    return basicInputsSection(section, report);
  }
  if (section.title === "Inherited From Business Underwriting") {
    const source = report.inherited_business_underwriting;
    const stageLabel = source?.source_stage_key === "screening" ? "Screening" : "Business Underwriting";
    const banner = source ? `
      <div class="source-guidance-box">
        <strong>Inherited From Latest Completed ${escapeHtml(stageLabel)} Report</strong>
        <p class="muted">${escapeHtml(source.title || `${stageLabel} report`)}${source.result ? ` • ${escapeHtml(source.result)}` : ""}</p>
      </div>
    ` : "";
    return compactMetadataSection(section, report, {
      banner,
      tableEditor: { badge: `Pulled from ${stageLabel}` },
    });
  }
  if (section.title === "Part I. Business Handoff And Delta Thesis") {
    return standardScreeningSection(section, report, {
      compactTextareas: true,
      inheritedBadge: "Read-only handoff",
    });
  }
  if (section.title === "Part II. Fast Kill Screen") return fastKillSection(section, report);
  if (section.title === "1. Evidence Coverage Check") return businessQuestionSection(section, report);
  if (section.title === "2. Evidence Log") return businessEvidenceLogSection(section, report);
  if (section.title === "3. Interaction Read") return standardScreeningSection(section, report, { compactTextareas: true });
  if (isManagementHardGateSection(section.title)) return hardGateSection(section, report);
  if (section.title === "Part V. Management Quality Snapshot") {
    return groupedTableSection(section, report, ["Rating", "Evidence Grade", "Source", "Confidence", "Notes"]);
  }
  if (section.title === "Management Hypothesis") {
    return standardScreeningSection(section, report, { compactTextareas: true, resultSpectrumLabels: ["Management Quality Result"] });
  }
  if (section.title === "2. Capital Allocation Timeline") return managementTimelineSection(section, report);
  if (section.title === "5. Acquisition, Divestiture, And Shutdown Record") return managementActionRecordSection(section, report);
  if (section.title === "1. Incentive And Agency Map") return managementIncentiveMapSection(section, report);
  if (section.title === "Part VIII. What Must Be True / What To Verify") return whatMustBeTrueSection(section, report);
  if (section.title === "2. Psychology And Bias Audit") return biasAuditSection(section, report);
  if (section.title === "Too Hard") return managementCategorySection(section, report);
  if (section.title === "Hard Gate Summary") {
    return groupedTableSection(section, report, ["Result", "Main Note"], { tableEditor: { compactTextarea: true } });
  }
  if (section.title === "Quality Summary") {
    return groupedTableSection(section, report, ["Rating", "Confidence"], { tableEditor: true });
  }
  if (section.title === "Final Decision") {
    return standardScreeningSection(section, report, { compact: true, compactTextareas: true, resultSpectrumLabels: ["Decision"] });
  }
  if (section.title === "One-Page Management Conclusion") return managementConclusionSection(section, report, schema);
  if ([
    "3. Retained-Capital Test",
    "4. Buyback And Issuance Review",
    "6. Risk Appetite And Balance Sheet Behavior",
  ].includes(section.title)) {
    return businessMixedSection(section, report);
  }
  return standardScreeningSection(section, report, { compactTextareas: true });
}

function isManagementHardGateSection(title) {
  return [
    "1. Integrity, Candor, And Accessibility",
    "2. Rational Capital Allocation And Countercyclicality",
    "3. Buybacks, Issuance, And Dilution Discipline",
    "4. Incentives, Compensation, And Agency",
    "5. Governance, Control, And Minority-Holder Treatment",
    "6. Management Depth, Delegation, And Culture",
    "7. Resistance To The Institutional Imperative And Empire Building",
  ].includes(title);
}

function managementTimelineSection(section, report) {
  const columns = ["Date", "Cycle context", "Stated rationale at the time", "Real alternative use of cash", "Result so far", "Evidence Grade", "Notes"];
  const rows = groupRepeatedTableFields(section.fields.filter((field) => field.label !== "Which decision best reflects rationality?" && field.label !== "Which decision most weakens the management case?" && field.label !== "Timeline Result"), columns);
  const trailingFields = section.fields.filter((field) => !columns.some((column) => field.label.endsWith(` - ${column}`)));
  const result = trailingFields.find((field) => field.label === "Timeline Result");
  const notes = trailingFields.filter((field) => field !== result);
  return `
    <div class="report-section" data-section-id="${section.id}">
      ${sectionHeader(section)}
      <div class="table-wrap">
        <table class="decision-table source-log-table">
          <thead><tr><th>Decision</th>${columns.map((column) => `<th>${escapeHtml(column)}</th>`).join("")}</tr></thead>
          <tbody>
            ${rows.map((row) => `
              <tr ${reportRowAttrs(columns.map((column) => row[column]).filter(Boolean), report)}>
                <td><strong>${escapeHtml(row.__rowLabel)}</strong></td>
                ${columns.map((column) => `<td>${row[column] ? tableFieldEditor(row[column], report, { compactTextarea: true }) : ""}</td>`).join("")}
              </tr>
            `).join("")}
          </tbody>
        </table>
      </div>
      ${notes.length ? `<div class="field-grid">${notes.map((field) => screeningFieldInput(field, report, { full: field.kind === "textarea", compactTextarea: true })).join("")}</div>` : ""}
      ${result ? `<div class="bold-result">${fieldQuestionLine(result)}${resultSpectrum(result, report)}</div>` : ""}
    </div>
  `;
}

function managementActionRecordSection(section, report) {
  const columns = ["Date", "Why management said it was done", "Price / consideration", "Did it improve per-share value?", "Evidence Grade", "Notes"];
  const rows = groupRepeatedTableFields(section.fields.filter((field) => field.label !== "Has management shown willingness to sell, shut, or shrink when economics fail?" && field.label !== "Is there evidence of \"do something\" bias or size worship?" && field.label !== "Were acquisitions small and digestible, or large and faith-based?" && field.label !== "Result"), columns);
  const result = section.fields.find((field) => field.label === "Result");
  const questions = section.fields.filter((field) => field.origin === "question");
  return `
    <div class="report-section" data-section-id="${section.id}">
      ${sectionHeader(section)}
      <div class="table-wrap">
        <table class="decision-table source-log-table">
          <thead><tr><th>Action</th>${columns.map((column) => `<th>${escapeHtml(column)}</th>`).join("")}</tr></thead>
          <tbody>
            ${rows.map((row) => `
              <tr ${reportRowAttrs(columns.map((column) => row[column]).filter(Boolean), report)}>
                <td><strong>${escapeHtml(row.__rowLabel)}</strong></td>
                ${columns.map((column) => `<td>${row[column] ? tableFieldEditor(row[column], report, { compactTextarea: true }) : ""}</td>`).join("")}
              </tr>
            `).join("")}
          </tbody>
        </table>
      </div>
      ${questionDropdownTable(questions, report)}
      ${result ? `<div class="bold-result">${fieldQuestionLine(result)}${resultSpectrum(result, report)}</div>` : ""}
    </div>
  `;
}

function managementIncentiveMapSection(section, report) {
  const columns = ["What are they paid for?", "What behavior does that encourage?", "How can it be gamed?", "Time horizon", "Risk level", "Notes"];
  const rows = groupRepeatedTableFields(section.fields.filter((field) => field.label !== "What incentive seems most dangerous?" && field.label !== "What incentive seems most aligned with owners?" && field.label !== "Incentive Result"), columns);
  const notes = section.fields.filter((field) => !columns.some((column) => field.label.endsWith(` - ${column}`)) && field.label !== "Incentive Result");
  const result = section.fields.find((field) => field.label === "Incentive Result");
  return `
    <div class="report-section" data-section-id="${section.id}">
      ${sectionHeader(section)}
      <div class="table-wrap">
        <table class="decision-table source-log-table">
          <thead><tr><th>Actor</th>${columns.map((column) => `<th>${escapeHtml(column)}</th>`).join("")}</tr></thead>
          <tbody>
            ${rows.map((row) => `
              <tr ${reportRowAttrs(columns.map((column) => row[column]).filter(Boolean), report)}>
                <td><strong>${escapeHtml(row.__rowLabel)}</strong></td>
                ${columns.map((column) => `<td>${row[column] ? tableFieldEditor(row[column], report, { compactTextarea: true }) : ""}</td>`).join("")}
              </tr>
            `).join("")}
          </tbody>
        </table>
      </div>
      ${notes.length ? `<div class="field-grid">${notes.map((field) => screeningFieldInput(field, report, { full: true, compactTextarea: true })).join("")}</div>` : ""}
      ${result ? `<div class="bold-result">${fieldQuestionLine(result)}${resultSpectrum(result, report)}</div>` : ""}
    </div>
  `;
}

function managementCategorySection(section, report) {
  const result = section.fields.find((field) => field.label === "Management Category Result") || section.fields.find(isResultField);
  const categories = [
    ["Exceptional Owner-Operators", "High integrity, strong owner orientation, excellent capital allocation, sensible buybacks and issuance, candid communication, real independence of thought.", "Can pass with smaller imperfections only if the record is long and governance is clean."],
    ["Rational Stewards", "Capable operators, sensible if not exceptional capital allocation, adequate candor, aligned enough incentives, acceptable governance.", "Can pass if no fatal misalignment remains and the per-share record is acceptable."],
    ["Capable But Agency-Risky", "Decent operators with mixed capital allocation and material compensation, buyback, issuance, acquisition, or governance concerns.", "Usually Watchlist unless the misalignment is narrow, verifiable, and fixable."],
    ["Promotional-Empire", "Narrative-heavy communication, deal activity favored over value, peer imitation, and EPS optics over per-share value.", "Archive unless there is clear and already visible change."],
    ["Control-Governance Risk", "Related-party issues, unequal treatment, weak board challenge, entrenchment, or opaque decision making.", "Archive unless governance risk is narrow, bounded, and remediable."],
    ["Too Hard", "Cannot identify the real decision maker, incentives are opaque, capital allocation is uninterpretable, or disclosures do not allow an owner-level judgment.", "Archive."],
  ];
  return `
    <div class="report-section" data-section-id="${section.id}">
      ${sectionHeader(section)}
      <div class="table-wrap">
        <table class="category-table">
          <thead><tr><th>Category</th><th>Traits</th><th>Management Standard</th></tr></thead>
          <tbody>
            ${categories.map((row, index) => `
              <tr class="category-row-${index + 1}">
                <td><strong>${escapeHtml(row[0])}</strong></td>
                <td>${escapeHtml(row[1])}</td>
                <td>${escapeHtml(row[2])}</td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      </div>
      ${result ? `<div class="bold-result">${fieldQuestionLine(result)}${resultSpectrum(result, report)}</div>` : ""}
    </div>
  `;
}

function managementConclusionSection(section, report, schema) {
  return `
    <div class="report-section" data-section-id="${section.id}">
      ${sectionHeader(section)}
      <div class="field-grid">
        ${section.fields.map((field) => {
          const derived = managementConclusionValue(field, report, schema);
          if (derived !== null) {
            return readonlyReportField(field, derived);
          }
          if (field.kind === "select" && isResultField(field)) {
            return `<div class="full bold-result">${fieldQuestionLine(field)}${resultSpectrum(field, report)}</div>`;
          }
          return screeningFieldInput(field, report, { compactTextarea: true });
        }).join("")}
      </div>
    </div>
  `;
}

function managementConclusionValue(field, report, schema) {
  const label = String(field.label || "").toLowerCase();
  const value = (sectionTitle, fieldLabel) => schemaFieldValue(report, schema, sectionTitle, fieldLabel);
  const inheritedCompany = value("Inherited From Business Underwriting", "Company") || report.company_name || "";
  const inheritedTicker = value("Inherited From Business Underwriting", "Ticker") || report.ticker || "";
  if (label === "company / ticker") return [inheritedCompany, inheritedTicker].filter(Boolean).join(" / ");
  if (label === "date") return value("Inherited From Business Underwriting", "Date");
  if (label === "decision") return value("Final Decision", "Decision");
  if (label === "management category") return value("Final Decision", "Management category") || value("Too Hard", "Management Category Result");
  if (label === "next funnel stage") return value("Final Decision", "Next funnel stage");
  if (label === "business claim inherited from business underwriting") return value("Inherited From Business Underwriting", "Main business claim proved");
  if (label === "main management question inherited") return value("Inherited From Business Underwriting", "Main question handed to Management Underwriting");
  if (label === "main financial underwriting task") return value("Final Decision", "Main Financial Underwriting task");
  return null;
}

function managementUnderwritingDecisionPanel(report) {
  const schema = report.template.schema || { sections: [] };
  const pass = schema.sections.find((section) => section.title === "If It Passes Management Underwriting");
  const watch = schema.sections.find((section) => section.title === "If It Goes To Watchlist");
  const archive = schema.sections.find((section) => section.title === "If It Is Archived");
  const decisionDescriptions = decisionDescriptionsFromCoreRules(schema);
  const selectedDecision = finalDecisionFromReport(report, schema);
  return `
    <section class="panel">
      <div class="panel-header">
        <div>
          <h3>Decision Output</h3>
          <p class="muted">Choose one management-underwriting destination. Only that destination remains editable.</p>
        </div>
      </div>
      <div class="panel-body grid decision-accordion">
        ${finalDecisionSpectrum(selectedDecision, schema)}
        ${pass ? destinationPanel(pass, report, "Pass Management Underwriting", "Pass", managementPassPanelContent(pass, report), selectedDecision === "Pass", decisionDescriptions.Pass) : ""}
        ${watch ? destinationPanel(watch, report, "Watchlist", "Watchlist", watchlistPanelContent(watch, report), selectedDecision === "Watchlist", decisionDescriptions.Watchlist) : ""}
        ${archive ? destinationPanel(archive, report, "Archive", "Archive", decisionPanelContent(archive, report), selectedDecision === "Archive", decisionDescriptions.Archive) : ""}
        <div class="button-row">
          ${reportSubmitButtons(report, { includeBack: true })}
        </div>
      </div>
    </section>
  `;
}

function managementPassPanelContent(section, report) {
  const requirements = bulletsAfterHeading(section.body_markdown, "Pass Management Underwriting requires:");
  const handoff = section.fields.filter((field) => field.label.startsWith("Business Underwriting handoff "));
  const downstream = section.fields.filter((field) => !field.label.startsWith("Business Underwriting handoff "));
  return `
    <div class="handoff-preview">
      <strong>Financial Underwriting Handoff</strong>
      <p class="muted">Carry forward the key management conclusions and unresolved issues for the next stage instead of rediscovering them later.</p>
    </div>
    ${requirements.length ? `
      <div class="source-guidance-box">
        <strong>Pass Management Underwriting requires</strong>
        <ul>${requirements.map((item) => `<li>${escapeHtml(stripInlineMarkdown(item))}</li>`).join("")}</ul>
      </div>
    ` : ""}
    <div class="source-guidance-box">
      <strong>Downstream Issues To Preserve</strong>
      <p class="muted">Preserve the residual management issue plus the specific Financial Underwriting, Valuation and Position Size, and Execution Rules work that still matters.</p>
    </div>
    <div class="field-grid">
      ${handoff.map((field) => screeningFieldInput(field, report, { full: true, compactTextarea: true })).join("")}
      ${downstream.map((field) => screeningFieldInput(field, report, { compact: true, compactTextarea: true })).join("")}
    </div>
  `;
}

function businessPassPanelContent(section, report) {
  const requirements = bulletsAfterHeading(section.body_markdown, "Pass Business Underwriting requires:");
  const handoff = section.fields.filter((field) => field.label.startsWith("Business Underwriting handoff "));
  const downstream = section.fields.filter((field) => !field.label.startsWith("Business Underwriting handoff "));
  return `
    <div class="handoff-preview">
      <strong>Management Underwriting Handoff</strong>
      <p class="muted">Carry forward the three most important business conclusions or open questions for the next stage.</p>
    </div>
    ${requirements.length ? `
      <div class="source-guidance-box">
        <strong>Pass Business Underwriting requires</strong>
        <ul>${requirements.map((item) => `<li>${escapeHtml(stripInlineMarkdown(item))}</li>`).join("")}</ul>
      </div>
    ` : ""}
    <div class="source-guidance-box">
      <strong>Downstream Issues To Preserve</strong>
      <p class="muted">Do not force later stages to rediscover the core business concerns. Preserve what Financial Underwriting, Valuation and Position Size, and Execution Rules still need to resolve.</p>
    </div>
    <div class="field-grid">
      ${handoff.map((field) => screeningFieldInput(field, report, { full: true, compactTextarea: true })).join("")}
      ${downstream.map((field) => screeningFieldInput(field, report, { compact: true, compactTextarea: true })).join("")}
    </div>
  `;
}

function renderFinancialUnderwritingReportEditor(report) {
  const template = report.template;
  const schema = template.schema || { sections: [], fields: [] };
  const sections = schema.sections.filter((section) => !skipFinancialUnderwritingSection(section));
  const selectedFinalDecision = finalDecisionFromReport(report, schema);
  content.innerHTML = `
    <form id="report-form" class="grid screening-report underwriting-report">
      <section class="panel">
        <div class="panel-header detail-head">
          <div>
            <button class="secondary" type="button" data-company-return="${report.company_id}">Back to Company</button>
            <p class="eyebrow">${escapeHtml(report.stage_name)}</p>
            <h3 class="company-title">${escapeHtml(report.title)}</h3>
            <p class="muted">Financial underwriting questionnaire. Sources, notes, and citations stay aligned with the Screening, Business Underwriting, and Management Underwriting workflow.</p>
          </div>
          <div class="button-row">
            <button class="danger" type="button" data-delete-report="${report.id}" data-company-id="${report.company_id}" data-report-title="${escapeAttr(report.title)}">Delete Report</button>
            ${reportSubmitButtons(report)}
          </div>
        </div>
        <div class="panel-body form-grid compact-form">
          <label>Title <input name="title" value="${escapeAttr(report.title)}" /></label>
          <label>Report month <input name="report_month" value="${escapeAttr(report.report_month || "")}" /></label>
          <input type="hidden" name="result" value="${escapeAttr(resultValueForFinalDecision(selectedFinalDecision) || report.result || "Draft")}" />
          <input type="hidden" name="review_date" value="${escapeAttr(report.review_date || "")}" />
        </div>
        ${reportQualityBanner(report)}
      </section>

      ${screeningSourcesPanel(report)}

      <section class="panel">
        <div class="panel-body">
          ${sections.map((section) => financialUnderwritingSection(section, report, schema)).join("")}
        </div>
      </section>

      ${financialUnderwritingDecisionPanel(report)}
    </form>
    ${fieldPopoverMarkup()}
    ${sourceDialogMarkup(report)}
    ${sourceDeleteDialogMarkup()}
    ${documentPreviewDialogMarkup()}
  `;
  initializeAnswerableReportSections(report, schema);
  bindScreeningReportEvents(report);
}

function skipFinancialUnderwritingSection(section) {
  const title = section.title || "";
  if (title.startsWith("Stock Candidate Financial Underwriting Questionnaire")) return true;
  if ([
    "Core Rules",
    "Evidence, Sources, And Confidence",
    "Part III. Financial Snapshot",
    "Part IV. Hard Financial Gates",
    "Part VI. Core Financial Worksheets",
    "Part IX. Munger Error-Prevention Checks",
    "Part X. Financial Pattern And Next Valuation Standard",
    "Category Options",
    "Asset-Light Compounder",
    "Good Predictable Business",
    "Asset-Heavy / Reinvestment-Heavy Business",
    "Cyclical / Commodity / Balance-Sheet-Sensitive Business",
    "Financial / Insurer",
    "Roll-Up / Serial Acquirer",
    "If It Passes Financial Underwriting",
    "If It Goes To Watchlist",
    "If It Is Archived",
    "If It Is Returned",
  ].includes(title)) return true;
  return !(section.fields || []).length;
}

function financialUnderwritingSection(section, report, schema) {
  if (section.title === "Basic Inputs") {
    return basicInputsSection(section, report);
  }
  if (section.title === "Inherited From Management Underwriting") return financialInheritedManagementSection(section, report);
  if (section.title === "Part I. Management Handoff And Delta Thesis") {
    return standardScreeningSection(section, report, { compactTextareas: true, inheritedBadge: "Read-only handoff" });
  }
  if (section.title === "Part II. Fast Financial Kill Screen") return fastKillSection(section, report);
  if (["1. Economics In Plain Numbers", "2. Why Does This Need Financial Underwriting?", "1. Inversion", "3. Financial Presentation Incentive Check"].includes(section.title)) {
    return standardScreeningSection(section, report, { compactTextareas: true });
  }
  if (isFinancialHardGateSection(section.title)) return hardGateSection(section, report);
  if (section.title === "Part V. Financial Quality Snapshot") {
    return financialMatrixSection(section, report, ["Rating", "Evidence Grade", "Source", "Confidence", "Notes"], "Financial Quality Result");
  }
  if ([
    "1. Multi-Year Financial Read",
    "2. Owner Earnings Worksheet",
    "3. Returns, Incremental Capital, And Margin Bridge",
    "4. Cash Conversion And Working Capital",
    "5. Balance Sheet Stress Snapshot",
    "6. Per-Share Value Creation And Retained-Capital Test",
    "7. Normalization Bridge",
  ].includes(section.title)) {
    return financialWorksheetSection(section, report);
  }
  if (section.title === "Part VII. Accounting And Red-Flag Log") {
    return financialMatrixSection(section, report, ["Status", "Severity", "Evidence Grade", "Source", "Notes / Next check"], "Red-Flag Read");
  }
  if (section.title === "Part VIII. What Must Be True / What To Verify") return whatMustBeTrueSection(section, report);
  if (section.title === "2. Psychology And Bias Audit") return biasAuditSection(section, report);
  if (section.title === "4. Base Rates And Outside View") return standardScreeningSection(section, report, { compactTextareas: true, resultSpectrumLabels: ["Munger Check Result"] });
  if (section.title === "Fragile / Promotional / Over-Leveraged") return financialCategorySection(section, report, schema);
  if (section.title === "Hard Gate Summary") {
    return groupedTableSection(section, report, ["Result", "Main Note"], { tableEditor: { compactTextarea: true } });
  }
  if (section.title === "Quality Summary") {
    return groupedTableSection(section, report, ["Rating", "Confidence"], { tableEditor: true });
  }
  if (section.title === "Final Decision") {
    return standardScreeningSection(section, report, { compact: true, compactTextareas: true, resultSpectrumLabels: ["Decision"] });
  }
  if (section.title === "One-Page Financial Underwriting Conclusion") return financialConclusionSection(section, report, schema);
  return standardScreeningSection(section, report, { compactTextareas: true });
}

function financialInheritedManagementSection(section, report) {
  const source = report.inherited_management_underwriting;
  const stageKey = source?.source_stage_key;
  const stageLabel = stageKey === "management_underwriting"
    ? "Management Underwriting"
    : stageKey === "business_underwriting"
      ? "Business Underwriting"
      : "Screening";
  const banner = source ? `
    <div class="source-guidance-box">
      <strong>Inherited From Latest Completed ${escapeHtml(stageLabel)} Report</strong>
      <p class="muted">${escapeHtml(source.title || `${stageLabel} report`)}${source.result ? ` • ${escapeHtml(source.result)}` : ""}</p>
    </div>
  ` : "";
  return compactMetadataSection(section, report, {
    banner,
    tableEditor: { badge: `Pulled from ${stageLabel}` },
  });
}

function isFinancialHardGateSection(title) {
  return [
    "1. Accounting Reality And Statement Cleanliness",
    "2. Owner Earnings And Cash Conversion",
    "3. Returns On Capital And Margin Quality",
    "4. Balance Sheet, Liquidity, And Permanent-Loss Risk",
    "5. Per-Share Economics, Dilution, And Retained-Capital Translation",
    "6. Cyclicality, Normalization, And Forecast Reliability",
    "7. Business-Type Fit And Specialist Financial Standard",
    "8. Ready For Valuation And Position Size",
  ].includes(title);
}

function financialMatrixSection(section, report, columns, resultLabel) {
  const rows = groupRepeatedTableFields(section.fields.filter((field) => field.label !== resultLabel), columns);
  const result = section.fields.find((field) => field.label === resultLabel);
  return `
    <div class="report-section" data-section-id="${section.id}">
      ${sectionHeader(section)}
      <div class="table-wrap">
        <table class="decision-table source-log-table">
          <thead><tr><th>Item</th>${columns.map((column) => `<th>${escapeHtml(column)}</th>`).join("")}</tr></thead>
          <tbody>
            ${rows.map((row) => `
              <tr ${reportRowAttrs(columns.map((column) => row[column]).filter(Boolean), report)}>
                <td><strong>${escapeHtml(row.__rowLabel)}</strong></td>
                ${columns.map((column) => `<td>${row[column] ? tableFieldEditor(row[column], report, { compactTextarea: true }) : ""}</td>`).join("")}
              </tr>
            `).join("")}
          </tbody>
        </table>
      </div>
      ${result ? `<div class="bold-result">${fieldQuestionLine(result)}${resultSpectrum(result, report)}</div>` : ""}
    </div>
  `;
}

function financialWorksheetSection(section, report) {
  const result = section.fields.find(isResultField);
  const fields = section.fields.filter((field) => field !== result);
  return `
    <div class="report-section" data-section-id="${section.id}">
      ${sectionHeader(section)}
      ${dataPointTable(fields, report, { tableEditor: { compactTextarea: true } })}
      ${result ? `<div class="bold-result">${fieldQuestionLine(result)}${resultSpectrum(result, report)}</div>` : ""}
    </div>
  `;
}

function financialCategorySection(section, report, schema) {
  const result = (schema.fields || []).find((field) => field.label === "Financial Pattern Result") || section.fields.find(isResultField);
  const categories = [
    ["Asset-Light Compounder", "High cash conversion, low maintenance capital needs, attractive returns on capital, and per-share value creation that does not depend on leverage.", "Use conservative owner earnings and test whether reinvestment and dilution are still supporting per-share value creation."],
    ["Good Predictable Business", "Understandable financials, stable cash conversion, acceptable returns, and balance-sheet resilience without unusual accounting complexity.", "Focus valuation on normalized owner earnings and guard against assuming more than the record supports."],
    ["Asset-Heavy / Reinvestment-Heavy Business", "Economics depend on replacement capex, disciplined reinvestment, and honest margin/capital accounting rather than headline earnings.", "Require realistic maintenance-capex, reinvestment, and cycle-normalization assumptions before valuation."],
    ["Cyclical / Commodity / Balance-Sheet-Sensitive Business", "Financial quality depends heavily on cycle position, fixed costs, leverage, working-capital swings, and stress survivability.", "Use normalized ranges, not spot earnings, and demand balance-sheet resilience."],
    ["Financial / Insurer", "Value rests on capital, funding, reserves or credit quality, underwriting discipline, and asset-liability matching rather than industrial-style margin analysis.", "Apply specialist capital and reserve standards before trusting valuation."],
    ["Roll-Up / Serial Acquirer", "Reported growth may be acquisition-led, with real economics hidden by adjustments, purchase accounting, or dilution.", "Separate organic from acquired economics and require per-share proof of value creation."],
    ["Fragile / Promotional / Over-Leveraged", "Accounting, leverage, dilution, or narrative dependence makes the numbers too fragile to anchor value confidently.", "Usually Watchlist or Archive unless one narrow issue is genuinely fixable."],
  ];
  return `
    <div class="report-section" data-section-id="${section.id}">
      ${sectionHeader(section)}
      <div class="table-wrap">
        <table class="category-table">
          <thead><tr><th>Pattern</th><th>Traits</th><th>Valuation Standard</th></tr></thead>
          <tbody>
            ${categories.map((row, index) => `
              <tr class="category-row-${index + 1}">
                <td><strong>${escapeHtml(row[0])}</strong></td>
                <td>${escapeHtml(row[1])}</td>
                <td>${escapeHtml(row[2])}</td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      </div>
      ${result ? `<div class="bold-result">${fieldQuestionLine(result)}${resultSpectrum(result, report)}</div>` : ""}
    </div>
  `;
}

function financialConclusionSection(section, report, schema) {
  return `
    <div class="report-section" data-section-id="${section.id}">
      ${sectionHeader(section)}
      <div class="field-grid">
        ${section.fields.map((field) => {
          const derived = financialConclusionValue(field, report, schema);
          if (derived !== null) {
            return readonlyReportField(field, derived);
          }
          if (field.kind === "select" && isResultField(field)) {
            return `<div class="full bold-result">${fieldQuestionLine(field)}${resultSpectrum(field, report)}</div>`;
          }
          return screeningFieldInput(field, report, { compactTextarea: true });
        }).join("")}
      </div>
    </div>
  `;
}

function financialConclusionValue(field, report, schema) {
  const label = String(field.label || "").toLowerCase();
  const value = (sectionTitle, fieldLabel) => schemaFieldValue(report, schema, sectionTitle, fieldLabel);
  const inheritedCompany = value("Inherited From Management Underwriting", "Company") || report.company_name || "";
  const inheritedTicker = value("Inherited From Management Underwriting", "Ticker") || report.ticker || "";
  if (label === "company / ticker") return [inheritedCompany, inheritedTicker].filter(Boolean).join(" / ");
  if (label === "date") return value("Basic Inputs", "Date") || value("Inherited From Management Underwriting", "Date");
  if (label === "decision") return value("Final Decision", "Decision");
  if (label === "financial pattern") return value("Final Decision", "Financial pattern") || value("Fragile / Promotional / Over-Leveraged", "Financial Pattern Result");
  if (label === "next funnel stage") return value("Final Decision", "Next funnel stage");
  if (label === "owner earnings view") return value("2. Owner Earnings Worksheet", "Result");
  if (label === "returns on capital view") return value("3. Returns, Incremental Capital, And Margin Bridge", "Result");
  if (label === "balance sheet view") return value("5. Balance Sheet Stress Snapshot", "Result");
  if (label === "per-share value-creation view") return value("6. Per-Share Value Creation And Retained-Capital Test", "Result");
  if (label === "normalization view") return value("7. Normalization Bridge", "Normalization Read");
  if (label === "main valuation and position size task") return value("If It Passes Financial Underwriting", "Business Underwriting handoff 1");
  if (label === "execution issue to preserve") return value("If It Passes Financial Underwriting", "Execution Rules issue");
  return null;
}

function financialUnderwritingDecisionPanel(report) {
  const schema = report.template.schema || { sections: [] };
  const pass = schema.sections.find((section) => section.title === "If It Passes Financial Underwriting");
  const watch = schema.sections.find((section) => section.title === "If It Goes To Watchlist");
  const archive = schema.sections.find((section) => section.title === "If It Is Archived");
  const returned = schema.sections.find((section) => section.title === "If It Is Returned");
  const decisionDescriptions = decisionDescriptionsFromCoreRules(schema);
  const selectedDecision = finalDecisionFromReport(report, schema);
  return `
    <section class="panel">
      <div class="panel-header">
        <div>
          <h3>Decision Output</h3>
          <p class="muted">Choose one financial-underwriting destination. Only that destination remains editable.</p>
        </div>
      </div>
      <div class="panel-body grid decision-accordion">
        ${finalDecisionSpectrum(selectedDecision, schema)}
        ${pass ? destinationPanel(pass, report, "Pass Financial Underwriting", "Pass", financialPassPanelContent(pass, report), selectedDecision === "Pass", decisionDescriptions.Pass) : ""}
        ${watch ? destinationPanel(watch, report, "Watchlist", "Watchlist", watchlistPanelContent(watch, report), selectedDecision === "Watchlist", decisionDescriptions.Watchlist) : ""}
        ${archive ? destinationPanel(archive, report, "Archive", "Archive", decisionPanelContent(archive, report), selectedDecision === "Archive", decisionDescriptions.Archive) : ""}
        ${returned ? destinationPanel(returned, report, "Return To Business Underwriting", "Return to Business Underwriting", financialReturnPanelContent(returned, report, "Business Underwriting"), selectedDecision === "Return to Business Underwriting", "Use this when the real blocker belongs in Business Underwriting, not in financial normalization.") : ""}
        ${returned ? destinationPanel(returned, report, "Return To Management Underwriting", "Return to Management Underwriting", financialReturnPanelContent(returned, report, "Management Underwriting"), selectedDecision === "Return to Management Underwriting", "Use this when the record is numerically analyzable but the key unresolved issue is management behavior, candor, incentives, or capital allocation.") : ""}
        <div class="button-row">
          ${reportSubmitButtons(report, { includeBack: true })}
        </div>
      </div>
    </section>
  `;
}

function financialPassPanelContent(section, report) {
  const requirements = bulletsAfterHeading(section.body_markdown, "Pass Financial Underwriting requires:");
  const handoff = section.fields.filter((field) => field.label.startsWith("Business Underwriting handoff "));
  const downstream = section.fields.filter((field) => !field.label.startsWith("Business Underwriting handoff "));
  return `
    <div class="handoff-preview">
      <strong>Valuation And Position Size Handoff</strong>
      <p class="muted">Carry forward the specific valuation questions that remain after the accounting, owner-earnings, and balance-sheet work is done.</p>
    </div>
    ${requirements.length ? `
      <div class="source-guidance-box">
        <strong>Pass Financial Underwriting requires</strong>
        <ul>${requirements.map((item) => `<li>${escapeHtml(stripInlineMarkdown(item))}</li>`).join("")}</ul>
      </div>
    ` : ""}
    <div class="source-guidance-box">
      <strong>Downstream Issues To Preserve</strong>
      <p class="muted">Do not force Valuation and Position Size or Execution Rules to rediscover unresolved normalization or sizing questions.</p>
    </div>
    <div class="field-grid">
      ${handoff.map((field) => screeningFieldInput(field, report, { full: true, compactTextarea: true })).join("")}
      ${downstream.map((field) => screeningFieldInput(field, report, { compact: true, compactTextarea: true })).join("")}
    </div>
  `;
}

function financialReturnPanelContent(section, report, stageLabel) {
  return `
    <div class="source-guidance-box">
      <strong>Return To ${escapeHtml(stageLabel)}</strong>
      <p class="muted">Use the return note to state exactly what prior-stage work must be redone or completed before Financial Underwriting can continue.</p>
    </div>
    ${standardPanelFields(section, report)}
  `;
}

function renderValuationPositionSizeReportEditor(report) {
  const template = report.template;
  const schema = template.schema || { sections: [], fields: [] };
  const sections = schema.sections.filter((section) => !skipValuationPositionSizeSection(section));
  const selectedFinalDecision = finalDecisionFromReport(report, schema);
  content.innerHTML = `
    <form id="report-form" class="grid screening-report underwriting-report">
      <section class="panel">
        <div class="panel-header detail-head">
          <div>
            <button class="secondary" type="button" data-company-return="${report.company_id}">Back to Company</button>
            <p class="eyebrow">${escapeHtml(report.stage_name)}</p>
            <h3 class="company-title">${escapeHtml(report.title)}</h3>
            <p class="muted">Valuation and position-size questionnaire. Sources, notes, and citations stay aligned with the Screening report workflow and the upstream underwriting stages.</p>
          </div>
          <div class="button-row">
            <button class="danger" type="button" data-delete-report="${report.id}" data-company-id="${report.company_id}" data-report-title="${escapeAttr(report.title)}">Delete Report</button>
            ${reportSubmitButtons(report)}
          </div>
        </div>
        <div class="panel-body form-grid compact-form">
          <label>Title <input name="title" value="${escapeAttr(report.title)}" /></label>
          <label>Report month <input name="report_month" value="${escapeAttr(report.report_month || "")}" /></label>
          <input type="hidden" name="result" value="${escapeAttr(resultValueForFinalDecision(selectedFinalDecision) || report.result || "Draft")}" />
          <input type="hidden" name="review_date" value="${escapeAttr(report.review_date || "")}" />
        </div>
        ${reportQualityBanner(report)}
      </section>

      ${screeningSourcesPanel(report)}

      <section class="panel">
        <div class="panel-body">
          ${sections.map((section) => valuationPositionSizeSection(section, report, schema)).join("")}
        </div>
      </section>

      ${valuationPositionSizeDecisionPanel(report)}
    </form>
    ${fieldPopoverMarkup()}
    ${sourceDialogMarkup(report)}
    ${sourceDeleteDialogMarkup()}
    ${documentPreviewDialogMarkup()}
  `;
  initializeAnswerableReportSections(report, schema);
  bindScreeningReportEvents(report);
}

function skipValuationPositionSizeSection(section) {
  const title = section.title || "";
  if (title.startsWith("Stock Candidate Valuation And Position Size Questionnaire")) return true;
  if ([
    "Core Rules",
    "Evidence, Sources, And Confidence",
    "Part III. Valuation Framing And Method Selection",
    "Part IV. Imported Normalized Economics And Assumption Quality",
    "Part V. Intrinsic Value Range And Price Ladder",
    "Part VI. Margin Of Safety, Expected Return, And Market-Implied Work",
    "Part VII. Downside, Risk, And Permanent-Loss Map",
    "Part VIII. Position Size Decision",
    "Part IX. Munger Error-Prevention Checks",
    "Part X. Business Category And Valuation Standard",
    "Category Options",
    "Exceptional Compounder",
    "Good Predictable Business",
    "Cyclical / Commodity / Asset-Heavy Business",
    "Financial / Insurer",
    "Special Situation",
    "If It Is Approved For Execution",
    "If It Goes To Watchlist",
    "If It Returns To Underwriting",
    "If It Is Archived",
  ].includes(title)) return true;
  return !(section.fields || []).length;
}

function valuationPositionSizeSection(section, report, schema) {
  if (section.title === "Basic Inputs") {
    return basicInputsSection(section, report);
  }
  if (section.title === "Inherited From Financial Underwriting") return valuationInheritedFinancialSection(section, report);
  if (section.title === "Part I. Financial Handoff And Valuation Delta Thesis") {
    return standardScreeningSection(section, report, { compactTextareas: true, inheritedBadge: "Read-only handoff" });
  }
  if (section.title === "Part II. Fast Kill Screen") return fastKillSection(section, report);
  if (section.title === "1. Value Drivers In Plain English") return standardScreeningSection(section, report, { compactTextareas: true });
  if (section.title === "2. Method Selection Decision") return valuationMethodSelectionSection(section, report);
  if (section.title === "1. Imported Economics From Financial Underwriting") return valuationImportedEconomicsSection(section, report);
  if (section.title === "2. Valuation-Specific Adjustments Only") {
    return financialMatrixSection(section, report, ["Inherited Stage-4 Treatment", "Valuation Adjustment Here", "Why Needed", "Evidence Grade", "Confidence", "Notes"], "Adjustment Read");
  }
  if (section.title === "3. Key Assumption Register") {
    return financialMatrixSection(section, report, ["Conservative", "Base", "Stretch", "Evidence Grade", "Confidence", "Why It Matters"], "Assumption Quality");
  }
  if (section.title === "4. Required Return And Discount Discipline") return standardScreeningSection(section, report, { compactTextareas: true });
  if (section.title === "1. Primary Valuation Workup") return financialWorksheetSection(section, report);
  if (section.title === "2. Enterprise To Equity Bridge") {
    return financialMatrixSection(section, report, ["Amount", "Notes"], "Bridge Result");
  }
  if (section.title === "3. Cross-Check Valuation Table") {
    return financialMatrixSection(section, report, ["Basis", "Value / Share", "Role", "Supports / Mixed / Contradicts", "Evidence Grade", "Notes"], "Cross-Check Result");
  }
  if (section.title === "4. Conservative Worth And Price Ladder") return valuationPriceLadderSection(section, report);
  if (section.title === "1. Margin Of Safety Test") return valuationMarginOfSafetySection(section, report);
  if (section.title === "2. Range And Sensitivity Table") return valuationSensitivitySection(section, report);
  if (section.title === "3. Market Expectations Check") return standardScreeningSection(section, report, { compactTextareas: true });
  if (section.title === "4. No-Rerating Return Check") return financialWorksheetSection(section, report);
  if (section.title === "1. Permanent-Loss Scenarios") return standardScreeningSection(section, report, { compactTextareas: true, resultSpectrumLabels: ["Risk Result"] });
  if (section.title === "2. Time Risk, Liquidity, And Balance-Sheet Endurance") return standardScreeningSection(section, report, { compactTextareas: true });
  if (section.title === "1. Sizing Inputs") return valuationSizingInputsSection(section, report);
  if (section.title === "2. Position Size Gate Table") {
    return groupedTableSection(section, report, ["Read", "Effect On Size"], { tableEditor: true });
  }
  if (section.title === "3. Buy, Add, And No-Buy Boundaries") return valuationBuyBoundarySection(section, report);
  if (section.title === "4. Concentration And Opportunity Cost") return standardScreeningSection(section, report, { compactTextareas: true, resultSpectrumLabels: ["Result"] });
  if (section.title === "1. False Precision Audit") return standardScreeningSection(section, report, { compactTextareas: true, resultSpectrumLabels: ["Result"] });
  if (section.title === "2. Psychology And Sizing Audit") return biasAuditSection(section, report);
  if (section.title === "3. Inversion") return standardScreeningSection(section, report, { compactTextareas: true, resultSpectrumLabels: ["Munger Check Result"] });
  if (section.title === "Too Hard") return valuationCategorySection(section, report, schema);
  if (section.title === "Hard Gate Summary") {
    return groupedTableSection(section, report, ["Result", "Main Note"], { tableEditor: { compactTextarea: true } });
  }
  if (section.title === "Quality Summary") {
    return groupedTableSection(section, report, ["Rating", "Confidence"], { tableEditor: true });
  }
  if (section.title === "Final Decision") {
    return standardScreeningSection(section, report, { compact: true, compactTextareas: true, resultSpectrumLabels: ["Decision"] });
  }
  if (section.title === "One-Page Valuation And Position Size Conclusion") return valuationConclusionSection(section, report, schema);
  return standardScreeningSection(section, report, { compactTextareas: true });
}

function valuationInheritedFinancialSection(section, report) {
  const source = report.inherited_financial_underwriting;
  const banner = source ? `
    <div class="source-guidance-box">
      <strong>Inherited From Latest Completed Financial Underwriting Report</strong>
      <p class="muted">${escapeHtml(source.title || "Financial Underwriting report")}${source.result ? ` • ${escapeHtml(source.result)}` : ""}</p>
    </div>
  ` : "";
  return compactMetadataSection(section, report, {
    banner,
    tableEditor: { badge: "Pulled from Financial Underwriting" },
  });
}

function valuationMethodSelectionSection(section, report) {
  const columns = ["Usually appropriate primary anchor", "Usually required cross-check", "Usually inappropriate as primary"];
  const result = section.fields.find((field) => field.label === "Result");
  const questions = section.fields.filter((field) => field.origin === "question");
  const guideFields = section.fields.filter((field) => columns.some((column) => field.label.endsWith(` - ${column}`)));
  const trailing = section.fields.filter((field) => field !== result && field.origin !== "question" && !guideFields.includes(field));
  const methodGuide = [
    ["Predictable non-financial business", "Owner earnings / FCFE / earning power", "No-rerating return, history, or sensible comparables", "Liquidation value alone"],
    ["Cyclical / commodity / asset-heavy business", "Normalized earnings power, trough-aware value, asset or replacement value", "Asset value, replacement cost, or cycle history", "Peak-year P/E or peak margin DCF"],
    ["Financial / insurer", "Book value, tangible book, distributable earnings, underwriting or spread economics, dividend or excess-capital logic", "Reserve / credit / capital adequacy cross-check", "EV / EBITDA or industrial-style owner-earnings shortcuts"],
    ["Leveraged or changing capital structure", "Enterprise value first, then bridge to equity", "Asset value, stress case, or debt-capacity cross-check", "Direct equity multiple without leverage bridge"],
    ["Sum-of-parts / special situation", "Private-market value, breakup value, event value, or SOTP", "Downside asset value or cash realization cross-check", "Single blended multiple with no segment logic"],
  ];
  return `
    <div class="report-section" data-section-id="${section.id}">
      ${sectionHeader(section)}
      <div class="table-wrap">
        <table class="decision-table source-log-table">
          <thead><tr><th>Situation</th>${columns.map((column) => `<th>${escapeHtml(column)}</th>`).join("")}</tr></thead>
          <tbody>
            ${methodGuide.map((row) => `
              <tr>
                <td><strong>${escapeHtml(row[0])}</strong></td>
                <td>${escapeHtml(row[1])}</td>
                <td>${escapeHtml(row[2])}</td>
                <td>${escapeHtml(row[3])}</td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      </div>
      ${questionDropdownTable(questions, report, { tableEditor: { compactTextarea: true } })}
      ${trailing.length ? `<div class="field-grid">${trailing.map((field) => screeningFieldInput(field, report, { full: field.kind === "textarea", compactTextarea: true })).join("")}</div>` : ""}
      ${result ? `<div class="bold-result">${fieldQuestionLine(result)}${resultSpectrum(result, report)}</div>` : ""}
    </div>
  `;
}

function valuationImportedEconomicsSection(section, report) {
  return financialWorksheetSection(section, report);
}

function valuationPriceLadderSection(section, report) {
  const result = section.fields.find((field) => field.label === "Price Ladder Read");
  const questions = section.fields.filter((field) => field.origin === "question");
  const fields = section.fields.filter((field) => field !== result && field.origin !== "question" && field.label !== "Answer");
  return `
    <div class="report-section" data-section-id="${section.id}">
      ${sectionHeader(section)}
      ${dataPointTable(fields, report, { tableEditor: { compactTextarea: true } })}
      ${questionDropdownTable(questions, report, { tableEditor: { compactTextarea: true } })}
      ${result ? `<div class="bold-result">${fieldQuestionLine(result)}${resultSpectrum(result, report)}</div>` : ""}
    </div>
  `;
}

function valuationMarginOfSafetySection(section, report) {
  const result = section.fields.find((field) => field.label === "Result");
  const questions = section.fields.filter((field) => field.origin === "question");
  const fields = section.fields.filter((field) => field !== result && field.origin !== "question");
  return `
    <div class="report-section" data-section-id="${section.id}">
      ${sectionHeader(section)}
      ${dataPointTable(fields, report, { tableEditor: { compactTextarea: true } })}
      ${questionDropdownTable(questions, report, { tableEditor: { compactTextarea: true } })}
      ${result ? `<div class="bold-result">${fieldQuestionLine(result)}${resultSpectrum(result, report)}</div>` : ""}
    </div>
  `;
}

function valuationSensitivitySection(section, report) {
  const columns = ["What Must Happen", "Value / Share", "3-Year Return From Current Price", "5-Year Return With No Rerating", "Notes"];
  const result = section.fields.find((field) => field.label === "Expected Return Result");
  const questions = section.fields.filter((field) => field.origin === "question");
  const rows = groupRepeatedTableFields(section.fields.filter((field) => field !== result && field.origin !== "question"), columns);
  return `
    <div class="report-section" data-section-id="${section.id}">
      ${sectionHeader(section)}
      <div class="table-wrap">
        <table class="decision-table source-log-table">
          <thead><tr><th>Case</th>${columns.map((column) => `<th>${escapeHtml(column)}</th>`).join("")}</tr></thead>
          <tbody>
            ${rows.map((row) => `
              <tr ${reportRowAttrs(columns.map((column) => row[column]).filter(Boolean), report)}>
                <td><strong>${escapeHtml(row.__rowLabel)}</strong></td>
                ${columns.map((column) => `<td>${row[column] ? tableFieldEditor(row[column], report, { compactTextarea: true }) : ""}</td>`).join("")}
              </tr>
            `).join("")}
          </tbody>
        </table>
      </div>
      ${questionDropdownTable(questions, report, { tableEditor: { compactTextarea: true } })}
      ${result ? `<div class="bold-result">${fieldQuestionLine(result)}${resultSpectrum(result, report)}</div>` : ""}
    </div>
  `;
}

function valuationSizingInputsSection(section, report) {
  const result = section.fields.find((field) => field.label === "Sizing Read");
  const questions = section.fields.filter((field) => field.origin === "question");
  const fields = section.fields.filter((field) => field !== result && field.origin !== "question");
  return `
    <div class="report-section" data-section-id="${section.id}">
      ${sectionHeader(section)}
      ${dataPointTable(fields, report, { tableEditor: { compactTextarea: true } })}
      ${questionDropdownTable(questions, report, { tableEditor: { compactTextarea: true } })}
      ${result ? `<div class="bold-result">${fieldQuestionLine(result)}${resultSpectrum(result, report)}</div>` : ""}
    </div>
  `;
}

function valuationBuyBoundarySection(section, report) {
  const result = section.fields.find((field) => field.label === "Boundary Read");
  const questions = section.fields.filter((field) => field.origin === "question");
  const fields = section.fields.filter((field) => field !== result && field.origin !== "question");
  return `
    <div class="report-section" data-section-id="${section.id}">
      ${sectionHeader(section)}
      ${dataPointTable(fields, report, { tableEditor: { compactTextarea: true } })}
      ${questionDropdownTable(questions, report, { tableEditor: { compactTextarea: true } })}
      ${result ? `<div class="bold-result">${fieldQuestionLine(result)}${resultSpectrum(result, report)}</div>` : ""}
    </div>
  `;
}

function valuationCategorySection(section, report, schema) {
  const result = (schema.fields || []).find((field) => field.label === "Business Category Result") || section.fields.find(isResultField);
  const categories = [
    ["Exceptional Compounder", "Unusually durable, high-return business with strong reinvestment quality and per-share value creation.", "Can justify a smaller discount than normal, but still needs a clear too-expensive line and a defensible no-rerating return."],
    ["Good Predictable Business", "Understandable economics with a decent value range, acceptable downside, and manageable uncertainty.", "Starter size can work at a visible discount; larger size needs a clearer gap to conservative worth."],
    ["Cyclical / Commodity / Asset-Heavy Business", "Value depends on normalized earnings power, trough resilience, cycle timing, or asset value rather than spot profits.", "Demand a larger discount, a stronger balance sheet, and extra caution on size."],
    ["Financial / Insurer", "Value rests on capital, reserves or credit, funding, and distributable economics rather than industrial-style shortcuts.", "Use the institution-specific valuation lens and size smaller when downside is hard to see."],
    ["Special Situation", "Value depends on an event path, deal terms, cash realization, or downside protection rather than steady compounding.", "Size only when the path to realization and the failure cost are both clear."],
    ["Too Hard", "The value range depends on fragile, circular, or opaque assumptions that cannot be defended conservatively.", "Stop here rather than manufacturing precision."],
  ];
  return `
    <div class="report-section" data-section-id="${section.id}">
      ${sectionHeader(section)}
      <div class="table-wrap">
        <table class="category-table">
          <thead><tr><th>Category</th><th>Traits</th><th>Valuation Standard</th></tr></thead>
          <tbody>
            ${categories.map((row, index) => `
              <tr class="category-row-${index + 1}">
                <td><strong>${escapeHtml(row[0])}</strong></td>
                <td>${escapeHtml(row[1])}</td>
                <td>${escapeHtml(row[2])}</td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      </div>
      ${result ? `<div class="bold-result">${fieldQuestionLine(result)}${resultSpectrum(result, report)}</div>` : ""}
    </div>
  `;
}

function valuationConclusionSection(section, report, schema) {
  return `
    <div class="report-section" data-section-id="${section.id}">
      ${sectionHeader(section)}
      <div class="field-grid">
        ${section.fields.map((field) => {
          const derived = valuationConclusionValue(field, report, schema);
          if (derived !== null) {
            return readonlyReportField(field, derived);
          }
          if (field.kind === "select" && isResultField(field)) {
            return `<div class="full bold-result">${fieldQuestionLine(field)}${resultSpectrum(field, report)}</div>`;
          }
          return screeningFieldInput(field, report, { compactTextarea: true });
        }).join("")}
      </div>
    </div>
  `;
}

function valuationConclusionValue(field, report, schema) {
  const label = String(field.label || "").toLowerCase();
  const value = (sectionTitle, fieldLabel) => schemaFieldValue(report, schema, sectionTitle, fieldLabel);
  const inheritedCompany = value("Inherited From Financial Underwriting", "Company") || report.company_name || "";
  const inheritedTicker = value("Inherited From Financial Underwriting", "Ticker") || report.ticker || "";
  const decision = value("Final Decision", "Decision");
  if (label === "company / ticker") return [inheritedCompany, inheritedTicker].filter(Boolean).join(" / ");
  if (label === "date") return value("Inherited From Financial Underwriting", "Date");
  if (label === "decision") return decision;
  if (label === "next funnel stage") return value("Final Decision", "Next funnel stage");
  if (label === "primary valuation method") return value("1. Primary Valuation Workup", "Method used") || value("2. Method Selection Decision", "Primary Method");
  if (label === "conservative worth per share") return value("Final Decision", "Conservative worth per share") || value("4. Conservative Worth And Price Ladder", "Conservative worth per share");
  if (label === "attractive price") return value("Final Decision", "Attractive price") || value("4. Conservative Worth And Price Ladder", "Attractive price for a starter or medium position");
  if (label === "clearly cheap enough to size up") return value("Final Decision", "Clearly cheap enough to size up") || value("4. Conservative Worth And Price Ladder", "Clearly cheap enough to size up");
  if (label === "too expensive, even if the business is excellent") return value("Final Decision", "Too expensive, even if the business is excellent") || value("4. Conservative Worth And Price Ladder", "Too expensive, even if the business is excellent");
  if (label === "current price") return value("Final Decision", "Current price") || value("Inherited From Financial Underwriting", "Current share price");
  if (label === "margin-of-safety view") return value("1. Margin Of Safety Test", "Result");
  if (label === "expected return without rerating") return value("4. No-Rerating Return Check", "Rough no-rerating return") || value("4. No-Rerating Return Check", "Result");
  if (label === "downside view") return value("1. Permanent-Loss Scenarios", "Risk Result") || value("Final Decision", "Main risk");
  if (label === "position-size view") return value("1. Sizing Inputs", "Sizing Read") || value("2. Position Size Gate Table", "Size Justification");
  if (label === "what valuation can safely assume") return value("Inherited From Financial Underwriting", "What valuation can safely assume");
  if (label === "what valuation must not assume") return value("Inherited From Financial Underwriting", "What valuation must not assume");
  if (label === "main thing to verify before buying") return value("Final Decision", "Main thing to verify before buying");
  if (label === "opportunity cost") return value("Final Decision", "Opportunity cost");
  if (label === "next action") {
    const normalizedDecision = normalizeFinalDecision(decision);
    if (normalizedDecision === "Approve For Execution") return "Open Execution Rules with the valuation guardrails above.";
    if (normalizedDecision === "Return To Underwriting") return value("If It Returns To Underwriting", "Immediate next checklist or memo");
    if (normalizedDecision === "Watchlist") return value("Final Decision", "Review date, if Watchlist");
    if (normalizedDecision === "Archive") return value("If It Is Archived", "What would need to change before revisiting?");
    return value("Final Decision", "Next funnel stage");
  }
  return null;
}

function valuationPositionSizeDecisionPanel(report) {
  const schema = report.template.schema || { sections: [] };
  const approve = schema.sections.find((section) => section.title === "If It Is Approved For Execution");
  const watch = schema.sections.find((section) => section.title === "If It Goes To Watchlist");
  const returned = schema.sections.find((section) => section.title === "If It Returns To Underwriting");
  const archive = schema.sections.find((section) => section.title === "If It Is Archived");
  const decisionDescriptions = decisionDescriptionsFromCoreRules(schema);
  const selectedDecision = finalDecisionFromReport(report, schema);
  return `
    <section class="panel">
      <div class="panel-header">
        <div>
          <h3>Decision Output</h3>
          <p class="muted">Choose one valuation destination. Only that destination remains editable.</p>
        </div>
      </div>
      <div class="panel-body grid decision-accordion">
        ${finalDecisionSpectrum(selectedDecision, schema)}
        ${approve ? destinationPanel(approve, report, "Approve For Execution", "Approve For Execution", valuationPassPanelContent(approve, report), selectedDecision === "Approve For Execution", decisionDescriptions["Approve For Execution"]) : ""}
        ${watch ? destinationPanel(watch, report, "Watchlist", "Watchlist", watchlistPanelContent(watch, report), selectedDecision === "Watchlist", decisionDescriptions.Watchlist) : ""}
        ${returned ? destinationPanel(returned, report, "Return To Underwriting", "Return To Underwriting", valuationReturnPanelContent(returned, report), selectedDecision === "Return To Underwriting", decisionDescriptions["Return To Underwriting"]) : ""}
        ${archive ? destinationPanel(archive, report, "Archive", "Archive", decisionPanelContent(archive, report), selectedDecision === "Archive", decisionDescriptions.Archive) : ""}
        <div class="button-row">
          ${reportSubmitButtons(report, { includeBack: true })}
        </div>
      </div>
    </section>
  `;
}

function valuationPassPanelContent(section, report) {
  const requirements = bulletsAfterHeading(section.body_markdown, "Approve For Execution requires:");
  const handoff = section.fields.filter((field) => field.label.startsWith("Business Underwriting handoff "));
  const guardrails = section.fields.filter((field) => !field.label.startsWith("Business Underwriting handoff "));
  return `
    <div class="handoff-preview">
      <strong>Execution Rules Handoff</strong>
      <p class="muted">Carry forward the valuation guardrails and sizing boundaries instead of forcing Execution Rules to recreate them.</p>
    </div>
    ${requirements.length ? `
      <div class="source-guidance-box">
        <strong>Approve For Execution requires</strong>
        <ul>${requirements.map((item) => `<li>${escapeHtml(stripInlineMarkdown(item))}</li>`).join("")}</ul>
      </div>
    ` : ""}
    <div class="field-grid">
      ${handoff.map((field) => screeningFieldInput(field, report, { full: true, compactTextarea: true })).join("")}
      ${guardrails.map((field) => screeningFieldInput(field, report, { compact: true, compactTextarea: true })).join("")}
    </div>
  `;
}

function valuationReturnPanelContent(section, report) {
  return `
    <div class="source-guidance-box">
      <strong>Return To Underwriting</strong>
      <p class="muted">Use the return memo to state exactly which upstream assumption is not trustworthy enough to support valuation today.</p>
    </div>
    ${standardPanelFields(section, report)}
  `;
}

function renderExecutionRulesReportEditor(report) {
  const template = report.template;
  const schema = template.schema || { sections: [], fields: [] };
  const sections = schema.sections.filter((section) => !skipExecutionRulesSection(section));
  const selectedFinalDecision = finalDecisionFromReport(report, schema);
  content.innerHTML = `
    <form id="report-form" class="grid screening-report underwriting-report">
      <section class="panel">
        <div class="panel-header detail-head">
          <div>
            <button class="secondary" type="button" data-company-return="${report.company_id}">Back to Company</button>
            <p class="eyebrow">${escapeHtml(report.stage_name)}</p>
            <h3 class="company-title">${escapeHtml(report.title)}</h3>
            <p class="muted">Execution rules questionnaire. Sources, notes, and citations stay aligned with the Screening report workflow while the valuation handoff remains visible and read-only.</p>
          </div>
          <div class="button-row">
            <button class="danger" type="button" data-delete-report="${report.id}" data-company-id="${report.company_id}" data-report-title="${escapeAttr(report.title)}">Delete Report</button>
            ${reportSubmitButtons(report)}
          </div>
        </div>
        <div class="panel-body form-grid compact-form">
          <label>Title <input name="title" value="${escapeAttr(report.title)}" /></label>
          <label>Report month <input name="report_month" value="${escapeAttr(report.report_month || "")}" /></label>
          <input type="hidden" name="result" value="${escapeAttr(resultValueForFinalDecision(selectedFinalDecision) || report.result || "Draft")}" />
          <input type="hidden" name="review_date" value="${escapeAttr(report.review_date || "")}" />
        </div>
        ${reportQualityBanner(report)}
      </section>

      ${screeningSourcesPanel(report)}

      <section class="panel">
        <div class="panel-body">
          ${sections.map((section) => executionRulesSection(section, report, schema)).join("")}
        </div>
      </section>

      ${executionRulesDecisionPanel(report)}
    </form>
    ${fieldPopoverMarkup()}
    ${sourceDialogMarkup(report)}
    ${sourceDeleteDialogMarkup()}
    ${documentPreviewDialogMarkup()}
  `;
  initializeAnswerableReportSections(report, schema);
  bindScreeningReportEvents(report);
}

function skipExecutionRulesSection(section) {
  const title = section.title || "";
  if (title.startsWith("Stock Candidate Execution Rules Questionnaire")) return true;
  if ([
    "Core Rules",
    "Evidence, Sources, And Confidence",
    "Part II. Complete Company Snapshot",
    "Part IV. Entry Rules",
    "Part V. Add, Scale-Up, And Average-Cost Rules",
    "Part VI. Hold, Trim, And Exit Rules",
    "Part VII. Monitoring And Return-To-Underwriting Triggers",
    "Part VIII. Portfolio Interaction, Concentration, And Opportunity Cost",
    "Category Options",
    "Immediate Starter",
    "Staged Accumulation",
    "Hold Existing / No Fresh Buying",
    "Watchlist Only",
    "Trim / Harvest",
    "Exit / Broken Thesis",
    "Too Hard To Execute",
    "Part XI. Decision Sheet",
    "If It Executes Now",
    "If It Enters Staged Orders",
    "If It Holds Existing",
    "If It Goes To Watchlist",
    "If It Returns To Underwriting",
    "If It Is Trimmed Or Exited",
    "If It Is Archived",
  ].includes(title)) return true;
  return !(section.fields || []).length;
}

function executionRulesSection(section, report, schema) {
  if (section.title === "Basic Inputs") {
    return basicInputsSection(section, report);
  }
  if (section.title === "Part I. Valuation Handoff And Execution Delta Thesis") {
    return executionValuationHandoffSection(section, report);
  }
  if (section.title === "1. Master Snapshot Table") {
    return executionMasterSnapshotSection(section, report);
  }
  if (section.title === "Part III. Fast Execution Kill Screen") return fastKillSection(section, report);
  if (section.title === "1. Trigger Table") return executionTriggerTableSection(section, report);
  if (section.title === "Part X. Execution Pattern And Standard") return executionPatternSection(section, report, schema);
  if (section.title === "Hard Gate Summary") {
    return groupedTableSection(section, report, ["Result", "Main Note"], { tableEditor: { compactTextarea: true } });
  }
  if (section.title === "Quality Summary") {
    return groupedTableSection(section, report, ["Rating", "Confidence"], { tableEditor: true });
  }
  if (section.title === "Final Decision") {
    return standardScreeningSection(section, report, { compact: true, compactTextareas: true, resultSpectrumLabels: ["Decision"] });
  }
  if (section.title === "One-Page Execution Conclusion") return executionConclusionSection(section, report, schema);
  if (section.title === "6. Valuation Snapshot") return executionValuationSnapshotSection(section, report);
  if (section.title === "5. Financial Snapshot" || section.title === "7. Position, Portfolio, And Liquidity Snapshot") {
    return standardScreeningSection(section, report, { compactTextareas: true, inheritedBadge: "Pulled from upstream work" });
  }
  if (section.title === "Part IX. Munger Error-Prevention Checks") {
    return standardScreeningSection(section, report, { compactTextareas: true, resultSpectrumLabels: ["Munger Check Result"] });
  }
  return standardScreeningSection(section, report, { compactTextareas: true });
}

function executionInheritedValuationBanner(report, label = "Latest completed Valuation and Position Size report") {
  const source = report.inherited_valuation_position_size;
  if (!source) return "";
  return `
    <div class="source-guidance-box">
      <strong>${escapeHtml(label)}</strong>
      <p class="muted">${escapeHtml(source.title || "Valuation and Position Size report")}${source.result ? ` • ${escapeHtml(source.result)}` : ""}</p>
    </div>
  `;
}

function executionValuationHandoffSection(section, report) {
  return `
    <div class="report-section" data-section-id="${section.id}">
      ${sectionHeader(section)}
      ${executionInheritedValuationBanner(report, "Inherited From Latest Completed Valuation and Position Size Report")}
      <div class="field-grid">
        ${section.fields.map((field) => {
          if (isResultField(field)) {
            return `<div class="full bold-result">${fieldQuestionLine(field)}${resultSpectrum(field, report)}</div>`;
          }
          return screeningFieldInput(field, report, { full: true, compactTextarea: true, inheritedBadge: "Read-only handoff" });
        }).join("")}
      </div>
    </div>
  `;
}

function executionMasterSnapshotSection(section, report) {
  const groups = groupFieldsByRow(section.fields, ["Value"]);
  return `
    <div class="report-section" data-section-id="${section.id}">
      ${sectionHeader(section)}
      ${executionInheritedValuationBanner(report)}
      <div class="table-wrap">
        <table class="decision-table data-point-table">
          <thead><tr><th>Item</th><th>Value</th></tr></thead>
          <tbody>
            ${Object.entries(groups).map(([rowLabel, fields]) => `
              <tr ${reportRowAttrs(Object.values(fields), report)}>
                <td>${escapeHtml(rowLabel)}</td>
                <td>${fields.Value ? tableFieldEditor(fields.Value, report, { compactTextarea: true }) : ""}</td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      </div>
    </div>
  `;
}

function executionValuationSnapshotSection(section, report) {
  return `
    <div class="report-section" data-section-id="${section.id}">
      ${sectionHeader(section)}
      ${executionInheritedValuationBanner(report)}
      <div class="field-grid">
        ${section.fields.map((field) => {
          if (isResultField(field)) {
            return `<div class="full bold-result">${fieldQuestionLine(field)}${resultSpectrum(field, report)}</div>`;
          }
          return screeningFieldInput(field, report, { full: true, compactTextarea: true, inheritedBadge: "Pulled from Valuation and Position Size" });
        }).join("")}
      </div>
    </div>
  `;
}

function executionTriggerTableSection(section, report) {
  const columns = ["Specific trigger", "Correct stage", "Review deadline"];
  const defaults = {
    Business: "Hold / Watchlist / Return / Exit Review",
    Management: "Hold / Watchlist / Return / Exit Review",
    Financial: "Hold / Watchlist / Return / Exit Review",
    "Valuation / price": "Buy / Hold / Trim / Watchlist",
    "Portfolio / liquidity": "Buy Smaller / Hold / Trim / Exit Review",
    "Governance / legal / control": "Hold / Return / Exit Review",
    "Capital allocation": "Hold / Return / Exit Review",
    "Financing / balance sheet": "Hold / Return / Exit Review",
  };
  const groups = groupFieldsByRow(section.fields, columns);
  return `
    <div class="report-section" data-section-id="${section.id}">
      ${sectionHeader(section)}
      <div class="table-wrap">
        <table class="decision-table">
          <thead><tr><th>Trigger Area</th><th>Specific Trigger</th><th>Default Action</th><th>Correct Stage</th><th>Review Deadline</th></tr></thead>
          <tbody>
            ${Object.entries(groups).map(([rowLabel, fields]) => `
              <tr ${reportRowAttrs(Object.values(fields), report)}>
                <td><strong>${escapeHtml(rowLabel)}</strong></td>
                <td>${fields["Specific trigger"] ? tableFieldEditor(fields["Specific trigger"], report, { compactTextarea: true }) : ""}</td>
                <td>${escapeHtml(defaults[rowLabel] || "")}</td>
                <td>${fields["Correct stage"] ? tableFieldEditor(fields["Correct stage"], report) : ""}</td>
                <td>${fields["Review deadline"] ? tableFieldEditor(fields["Review deadline"], report, { compactTextarea: true }) : ""}</td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      </div>
    </div>
  `;
}

function executionPatternSection(section, report, schema) {
  const result = (section.fields || []).find((field) => field.label === "Execution Pattern Result")
    || (schema.fields || []).find((field) => field.label === "Execution Pattern Result");
  const patterns = [
    ["Immediate Starter", "Current price is inside the approved starter range, liquidity is manageable, and no major near-term fact makes the valuation stale.", "Buy now only inside the defined price, size, and order rules.", "Review at the next defined event or price trigger, not because of ordinary noise."],
    ["Staged Accumulation", "The thesis is actionable, but liquidity, uncertainty, or size discipline requires several tranches.", "Use a written tranche plan with maximum capital per tranche, timing rules, and invalidation rules.", "Recheck facts between tranches instead of completing the ladder automatically."],
    ["Hold Existing / No Fresh Buying", "The company is still ownable, but the current price or opportunity cost does not justify fresh buying.", "Hold according to the written review cadence and reopen buying only if price or facts improve.", "Focus on thesis integrity, valuation drift, and position-size discipline."],
    ["Watchlist Only", "Price, liquidity, evidence, or opportunity cost is not good enough yet, but a specific trigger can be named.", "No order now. Write the trigger and review when it is hit.", "Monitor only the stated trigger, not daily noise."],
    ["Trim / Harvest", "The position is too large, too expensive, or clearly inferior to another use of capital.", "Trim according to the written size and valuation rules. Avoid improvisation.", "Reassess whether further trimming or a full exit is needed after the first reduction."],
    ["Exit / Broken Thesis", "Business, management, financial integrity, or downside tolerance is broken enough that ownership is no longer acceptable.", "Sell according to the written exit rule. Do not negotiate with a broken thesis.", "Archive unless a clearly new case is rebuilt from the correct earlier stage."],
    ["Too Hard To Execute", "Listing, liquidity, tax, mandate, event, or knowledge constraints prevent sensible action.", "Do not force a trade.", "Revisit only if the blocking execution constraint changes."],
  ];
  return `
    <div class="report-section" data-section-id="${section.id}">
      ${sectionHeader(section)}
      <div class="table-wrap">
        <table class="category-table">
          <thead><tr><th>Pattern</th><th>Traits</th><th>Execution Standard</th><th>Monitoring Standard</th></tr></thead>
          <tbody>
            ${patterns.map((row, index) => `
              <tr class="category-row-${index + 1}">
                <td><strong>${escapeHtml(row[0])}</strong></td>
                <td>${escapeHtml(row[1])}</td>
                <td>${escapeHtml(row[2])}</td>
                <td>${escapeHtml(row[3])}</td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      </div>
      ${result ? `<div class="bold-result">${fieldQuestionLine(result)}${resultSpectrum(result, report)}</div>` : ""}
    </div>
  `;
}

function executionMasterValue(report, schema, label) {
  return schemaFieldValue(report, schema, "1. Master Snapshot Table", `${label} - Value`);
}

function executionConclusionSection(section, report, schema) {
  return `
    <div class="report-section" data-section-id="${section.id}">
      ${sectionHeader(section)}
      <div class="field-grid">
        ${section.fields.map((field) => {
          const derived = executionConclusionValue(field, report, schema);
          if (derived !== null) {
            return readonlyReportField(field, derived);
          }
          if (field.kind === "select" && isResultField(field)) {
            return `<div class="full bold-result">${fieldQuestionLine(field)}${resultSpectrum(field, report)}</div>`;
          }
          return screeningFieldInput(field, report, { compactTextarea: true });
        }).join("")}
      </div>
    </div>
  `;
}

function executionConclusionValue(field, report, schema) {
  const label = String(field.label || "").toLowerCase();
  const value = (sectionTitle, fieldLabel) => schemaFieldValue(report, schema, sectionTitle, fieldLabel);
  const master = (fieldLabel) => executionMasterValue(report, schema, fieldLabel);
  const decision = value("Final Decision", "Decision");
  if (label === "company / ticker") {
    const company = master("Company") || report.company_name || "";
    const ticker = master("Ticker / exchange") || report.ticker || "";
    return [company, ticker].filter(Boolean).join(" / ");
  }
  if (label === "date") return master("Date of last Valuation and Position Size memo");
  if (label === "decision") return decision;
  if (label === "execution pattern") return value("Final Decision", "Execution pattern") || value("Part X. Execution Pattern And Standard", "Execution Pattern Result");
  if (label === "next action") return value("Final Decision", "Next action");
  if (label === "what the business is") return value("3. Business Snapshot", "What does the company actually sell?");
  if (label === "why own it") return value("Final Decision", "Primary reason");
  if (label === "why not own it") return value("Final Decision", "Main risk");
  if (label === "business quality summary") return value("3. Business Snapshot", "Business Snapshot Result") || value("3. Business Snapshot", "What evidence most supports the business quality?");
  if (label === "management quality summary") return value("4. Management Snapshot", "Management Snapshot Result") || value("4. Management Snapshot", "What is the strongest evidence of integrity and candor?");
  if (label === "financial quality summary") return value("5. Financial Snapshot", "Financial Snapshot Result") || value("5. Financial Snapshot", "What is the main financial strength?");
  if (label === "conservative worth per share") return value("Final Decision", "Conservative worth per share") || master("Conservative worth per share");
  if (label === "base worth per share") return value("Final Decision", "Base worth per share") || master("Base worth per share");
  if (label === "high worth per share") return value("Final Decision", "High worth per share") || master("High worth per share");
  if (label === "attractive / starter buy range") return value("Final Decision", "Attractive / starter buy range") || master("Attractive / starter buy range");
  if (label === "clearly cheap enough to size up") return value("Final Decision", "Clearly cheap enough to size up") || master("Clearly cheap enough to size up");
  if (label === "no-buy-above line") return value("Final Decision", "No-buy-above line") || master("No-buy-above line");
  if (label === "current price") return value("Final Decision", "Current price") || master("Current share price");
  if (label === "current discount or premium to conservative worth") return value("6. Valuation Snapshot", "What is the current price, and what discount or premium does it imply to conservative worth?");
  if (label === "market cap / enterprise value") {
    const marketCap = master("Market cap");
    const enterpriseValue = master("Enterprise value");
    return [marketCap ? `Market cap: ${marketCap}` : "", enterpriseValue ? `Enterprise value: ${enterpriseValue}` : ""].filter(Boolean).join(" / ");
  }
  if (label === "existing position") return master("Existing position size");
  if (label === "target weight") return value("Final Decision", "New target weight") || master("Proposed starter size");
  if (label === "hard max weight") return value("Final Decision", "Hard max weight") || master("Hard max size");
  if (label === "order plan") return value("Final Decision", "Planned order construction") || value("2. Order Construction", "What order style will be used: limit, staged limits, manual accumulation, VWAP-style discipline, or something else?");
  if (label === "hold rule") return value("1. Hold Rules", "Under what conditions is the correct action to hold without buying more?");
  if (label === "trim rule") return value("2. Trim Rules", "At what valuation stretch does trimming become the default?");
  if (label === "exit rule") return value("3. Full Exit Rules", "What exact facts trigger immediate exit?");
  if (label === "main fact that would stop buying") return value("Final Decision", "Main fact that would stop buying");
  if (label === "main fact that would force exit") return value("Final Decision", "Main fact that would force exit");
  if (label === "what forces return to underwriting") {
    return value("If It Returns To Underwriting", "Specific assumption that cannot be trusted today")
      || value("Part I. Valuation Handoff And Execution Delta Thesis", "What single fact would stop all buying immediately?");
  }
  if (label === "main monitoring focus") {
    return value("6. Monitoring Cadence", "What event requires an immediate off-cycle review?")
      || value("2. Business Triggers", "Which KPI, market-share, customer, pricing, or competitive changes would send the company back to Business Underwriting?");
  }
  if (label === "opportunity cost") return value("Final Decision", "Opportunity cost") || value("2. Opportunity Cost", "What is the best alternative use of the same capital today?");
  return null;
}

function executionRulesDecisionPanel(report) {
  const schema = report.template.schema || { sections: [] };
  const executeNow = schema.sections.find((section) => section.title === "If It Executes Now");
  const staged = schema.sections.find((section) => section.title === "If It Enters Staged Orders");
  const hold = schema.sections.find((section) => section.title === "If It Holds Existing");
  const watch = schema.sections.find((section) => section.title === "If It Goes To Watchlist");
  const returned = schema.sections.find((section) => section.title === "If It Returns To Underwriting");
  const trimExit = schema.sections.find((section) => section.title === "If It Is Trimmed Or Exited");
  const archive = schema.sections.find((section) => section.title === "If It Is Archived");
  const decisionDescriptions = decisionDescriptionsFromCoreRules(schema);
  const selectedDecision = finalDecisionFromReport(report, schema);
  const trimExitDescription = selectedDecision === "Exit" ? decisionDescriptions.Exit : decisionDescriptions.Trim;
  return `
    <section class="panel">
      <div class="panel-header">
        <div>
          <h3>Decision Output</h3>
          <p class="muted">Choose one execution outcome. Only the active destination stays editable.</p>
        </div>
      </div>
      <div class="panel-body grid decision-accordion">
        ${finalDecisionSpectrum(selectedDecision, schema)}
        ${executeNow ? destinationPanel(executeNow, report, "Execute Starter Now", "Execute Starter Now", executionExecuteNowPanelContent(executeNow, report), selectedDecision === "Execute Starter Now", decisionDescriptions["Execute Starter Now"]) : ""}
        ${staged ? destinationPanel(staged, report, "Enter Staged Orders", "Enter Staged Orders", executionStagedOrdersPanelContent(staged, report), selectedDecision === "Enter Staged Orders", decisionDescriptions["Enter Staged Orders"]) : ""}
        ${hold ? destinationPanel(hold, report, "Hold Existing", "Hold Existing", executionHoldExistingPanelContent(hold, report), selectedDecision === "Hold Existing", decisionDescriptions["Hold Existing"]) : ""}
        ${watch ? destinationPanel(watch, report, "Watchlist", "Watchlist", watchlistPanelContent(watch, report), selectedDecision === "Watchlist", decisionDescriptions.Watchlist) : ""}
        ${returned ? destinationPanel(returned, report, "Return To Underwriting", "Return To Underwriting", valuationReturnPanelContent(returned, report), selectedDecision === "Return To Underwriting", decisionDescriptions["Return To Underwriting"]) : ""}
        ${trimExit ? destinationPanel(trimExit, report, "Trim / Exit", "Trim|Exit", executionTrimExitPanelContent(trimExit, report), selectedDecision === "Trim" || selectedDecision === "Exit", trimExitDescription) : ""}
        ${archive ? destinationPanel(archive, report, "Archive", "Archive", decisionPanelContent(archive, report), selectedDecision === "Archive", decisionDescriptions.Archive) : ""}
        <div class="button-row">
          ${reportSubmitButtons(report, { includeBack: true })}
        </div>
      </div>
    </section>
  `;
}

function executionExecuteNowPanelContent(section, report) {
  const requirements = bulletsAfterHeading(section.body_markdown, "Execute Starter Now requires:");
  return `
    <div class="handoff-preview">
      <strong>Immediate Execution Plan</strong>
      <p class="muted">Use the valuation guardrails as fixed inputs and define only the exact starter plan that will be followed.</p>
    </div>
    ${requirements.length ? `
      <div class="source-guidance-box">
        <strong>Execute Starter Now requires</strong>
        <ul>${requirements.map((item) => `<li>${escapeHtml(stripInlineMarkdown(item))}</li>`).join("")}</ul>
      </div>
    ` : ""}
    ${standardPanelFields(section, report)}
  `;
}

function executionStagedOrdersPanelContent(section, report) {
  return `
    <div class="source-guidance-box">
      <strong>Staged Orders</strong>
      <p class="muted">Commit the tranche plan and the invalidation rule now so the ladder is not finished automatically after the facts change.</p>
    </div>
    ${standardPanelFields(section, report)}
  `;
}

function executionHoldExistingPanelContent(section, report) {
  return `
    <div class="source-guidance-box">
      <strong>Hold Existing</strong>
      <p class="muted">Define the no-fresh-buy line, the trim trigger, and the next review trigger explicitly so “hold” does not become passive drift.</p>
    </div>
    ${standardPanelFields(section, report)}
  `;
}

function executionTrimExitPanelContent(section, report) {
  return `
    <div class="source-guidance-box">
      <strong>Trim / Exit Discipline</strong>
      <p class="muted">State whether the sale is valuation-, sizing-, or thesis-driven, and what would need to happen before re-entry is even considered.</p>
    </div>
    ${standardPanelFields(section, report)}
  `;
}

function screeningFieldInput(field, report, options = {}) {
  if (isAutoInheritedField(report, field.id)) {
    return inheritedReadonlyField(field, report, options);
  }
  const full = options.full || field.kind === "textarea" ? "full" : "";
  return `
    <label class="${full}" ${reportFieldWrapperAttrs(field, report)}>
      ${fieldQuestionLine(field)}
      ${screeningFieldControl(field, report, options)}
    </label>
  `;
}

function screeningFieldControl(field, report, options = {}) {
  const value = fieldValue(field, report);
  const attrs = `data-field-id="${escapeAttr(field.id)}" data-field-kind="${escapeAttr(field.kind)}"`;
  const money = shouldUseMoneyInput(field) ? " data-money-input=\"1\"" : "";
  if (field.kind === "select") {
    const selectOptions = [`<option value=""></option>`].concat(filteredOptions(field.options || []).map((item) => {
      const selected = String(value) === String(item) ? "selected" : "";
      return `<option value="${escapeAttr(item)}" ${selected}>${escapeHtml(item)}</option>`;
    }));
    return `<select ${attrs}>${selectOptions.join("")}</select>`;
  }
  if (field.kind === "checkbox") {
    const checked = value === "true" || value === true ? "checked" : "";
    return `<input type="checkbox" ${attrs} value="true" ${checked} />`;
  }
  if (field.kind === "textarea") {
    return `<textarea rows="1" ${attrs} data-autosize-textarea="1">${escapeHtml(value)}</textarea>`;
  }
  if (field.kind === "date") {
    return `<input type="date" value="${escapeAttr(value)}" ${attrs} />`;
  }
  const controlValue = shouldUseMoneyInput(field) ? normalizeMoneyDisplay(value) : value;
  return `<input value="${escapeAttr(controlValue)}" ${attrs}${money} />`;
}

function fieldQuestionLine(field, options = {}) {
  const label = displayFieldLabel(field.label);
  return `
    <span class="question-line">
      <span>${escapeHtml(label)}</span>
      ${options.hideTools ? "" : `<span class="field-tools">${fieldToolButtons(field, label)}</span>`}
    </span>
  `;
}

function sourceButtonControl(field) {
  const label = displayFieldLabel(field.label);
  return `
    <div class="mini-field-tools source-cell-tools" ${reportFieldWrapperAttrs(field, state.currentReport || {})}>
      <button type="button" class="inline-tool source-cell-button" data-source-field="${escapeAttr(field.id)}" data-field-label="${escapeAttr(label)}">
        Sources ${fieldSourceCount(field.id)}
      </button>
      <button type="button" class="inline-tool ${fieldHasNote(field.id) || fieldHasException(field.id) ? "has-note" : ""}" data-note-field="${escapeAttr(field.id)}" data-field-label="${escapeAttr(label)}">
        ${fieldNoteButtonLabel(field)}
      </button>
    </div>
  `;
}

function displayFieldLabel(label) {
  return String(label || "")
    .replace(/\s+or\s+Redirect/gi, "")
    .replace(/Redirect\s+or\s+/gi, "")
    .trim();
}

function fieldSourceCount(fieldId) {
  const entry = state.fieldSources[fieldId] || {};
  const count = (entry.source_ids || []).length;
  return count ? `(${count})` : "";
}

function currentReportField(fieldId) {
  return state.currentReport?.template?.schema?.field_lookup?.by_id?.[fieldId]
    || (state.currentReport?.template?.schema?.fields || []).find((field) => field.id === fieldId)
    || null;
}

function fieldNotesRequired(fieldOrId) {
  const field = typeof fieldOrId === "string" ? currentReportField(fieldOrId) : fieldOrId;
  return Boolean(field?.notes_required);
}

function fieldNoteButtonLabel(fieldOrId) {
  return fieldNotesRequired(fieldOrId) ? "Notes*" : "Notes";
}

function fieldNotePlaceholder(fieldId) {
  return currentReportField(fieldId)?.note_placeholder || "Optional: capture caveats, uncertainty, assumptions, or audit-trail context for this response.";
}

function fieldNoteRequirementHelp(fieldId) {
  if (fieldNotesRequired(fieldId)) {
    return "Required for this field. Capture the basis, derivation, or decision logic behind the answer.";
  }
  return "Optional for narrative fields. Use notes for caveats, uncertainty, or audit trail when they add value.";
}

function fieldHasNote(fieldId) {
  return Boolean((state.fieldNotes[fieldId] || "").trim());
}

function fieldExceptionStatus(fieldId) {
  return String(state.fieldExceptions[fieldId] || "").trim();
}

function fieldHasException(fieldId) {
  return Boolean(fieldExceptionStatus(fieldId));
}

function radioCell(field, option, report, options = {}) {
  if (isRedirectOption(option)) return "";
  const checked = fieldValue(field, report) === option ? "checked" : "";
  return `<td><label class="radio-cell${options.hideLabel ? " radio-cell-compact" : ""}"><input type="radio" name="${escapeAttr(field.id)}" data-field-id="${escapeAttr(field.id)}" data-field-kind="${escapeAttr(field.kind)}" value="${escapeAttr(option)}" ${checked} aria-label="${escapeAttr(option)}" /><span class="${options.hideLabel ? "visually-hidden" : ""}">${escapeHtml(option)}</span></label></td>`;
}

function resultSpectrum(field, report) {
  const options = filteredOptions(field.options?.length ? field.options : ["Strong", "Adequate", "Weak", "Unknown"]);
  const value = fieldValue(field, report);
  return `
    <div class="result-spectrum" data-spectrum-options="${options.length}">
      ${options.map((option, index) => {
        const checked = value === option ? "checked" : "";
        return `<label><input type="radio" name="${escapeAttr(field.id)}" data-field-id="${escapeAttr(field.id)}" data-field-kind="${escapeAttr(field.kind)}" value="${escapeAttr(option)}" ${checked} /><span class="spectrum-${index + 1} tone-${spectrumTone(option)}">${escapeHtml(option)}</span></label>`;
      }).join("")}
    </div>
  `;
}

function checkboxField(field, report) {
  const checked = fieldValue(field, report) === "true" || fieldValue(field, report) === true ? "checked" : "";
  return `<label class="checkbox-row" ${reportFieldWrapperAttrs(field, report)}><input type="checkbox" data-field-id="${escapeAttr(field.id)}" data-field-kind="checkbox" value="true" ${checked} /><span>${escapeHtml(field.label)}</span></label>`;
}

function fieldValue(field, report) {
  const responses = report.responses || {};
  const metrics = report.metrics || {};
  const primary = field.kind === "metric" || field.kind === "number" ? metrics : responses;
  const fallback = field.kind === "metric" || field.kind === "number" ? responses : metrics;
  return primary[field.id] ?? fallback[field.id] ?? "";
}

function filteredOptions(options) {
  return (options || []).filter((option) => !isRedirectOption(option));
}

function isRedirectOption(option) {
  return String(option || "").trim().toLowerCase() === "redirect";
}

function spectrumTone(option) {
  const value = String(option || "").toLowerCase();
  if (value.includes("approve") || value.includes("pass") || value.includes("continue") || value.includes("clear") || value.includes("strong") || value.includes("attractive") || value.includes("robust") || value.includes("execute starter") || value.includes("enter staged")) return "pass";
  if (value.includes("return") || value.includes("watchlist") || value.includes("needs verification") || value.includes("adequate") || value.includes("potentially") || value.includes("reasonable") || value.includes("thin") || value.includes("some fragility") || value.includes("hold existing") || value.includes("buy small only") || value === "trim") return "watchlist";
  if (value.includes("archive") || value.includes("too hard") || value.includes("weak") || value.includes("too expensive") || value.includes("none") || value.includes("unknowable") || value.includes("unknown") || value.includes("fragile") || value === "exit" || value.includes("exit review")) return "archive";
  return "neutral";
}

function customField(sectionId, label, kind, options) {
  return {
    id: `custom-${sectionId}-${slugify(label)}`,
    label,
    kind,
    options,
    section_id: sectionId,
  };
}

function isResultField(field) {
  return field.kind === "select" && (/(\bresult|\bread|\bdecision)$/i.test(field.label) || /result$/i.test(field.label));
}

function shouldUseMoneyInput(field) {
  const section = (field.section_id || "").toLowerCase();
  return field.kind === "metric" && (
    section.includes("normalized-economics") ||
    section.includes("simple-valuation-markers") ||
    section.includes("rough-value-range") ||
    section.includes("apparent-margin") ||
    section.includes("market-expectations") ||
    section.includes("no-rerating")
  );
}

function normalizeMoneyDisplay(value) {
  const text = String(value || "").trim();
  if (!text) return "";
  return text.startsWith("$") ? text : `$${text}`;
}

function isPartVISection(section, schema) {
  const index = schema.sections.findIndex((item) => item.id === section.id);
  const partVI = schema.sections.findIndex((item) => item.title === "Part VI. Price And Valuation Sanity Check");
  const partVII = schema.sections.findIndex((item) => item.title === "Part VII. What Must Be True / What To Verify");
  return partVI >= 0 && index > partVI && (partVII < 0 || index < partVII);
}

function isHardGateSection(section, schema) {
  const index = schema.sections.findIndex((item) => item.id === section.id);
  const partIII = schema.sections.findIndex((item) => item.title === "Part III. Hard Screening Gates");
  const partIV = schema.sections.findIndex((item) => item.title === "Part IV. Business Quality Snapshot");
  return partIII >= 0 && index > partIII && (partIV < 0 || index < partIV);
}

function hardGateRuleRows(markdown) {
  return bulletsAfterHeading(markdown, "Rule:").map((item) => {
    const cleaned = stripInlineMarkdown(item);
    const match = cleaned.match(/^(Pass|Watchlist|Archive|Redirect)\s+if\s+(.+)$/i);
    if (!match) return { option: cleaned.split(/\s+/)[0] || "Rule", guidance: cleaned };
    return { option: match[1], guidance: match[2] };
  }).filter((row) => !isRedirectOption(row.option));
}

function decisionClass(option) {
  const normalized = String(option || "").toLowerCase();
  if (normalized.includes("pass") || normalized.includes("clear")) return "green";
  if (normalized.includes("watch") || normalized.includes("verify")) return "amber";
  if (normalized.includes("archive") || normalized.includes("weak")) return "red";
  return "";
}

function stripInlineMarkdown(value) {
  return String(value || "")
    .replace(/\*\*(.*?)\*\*/g, "$1")
    .replace(/`(.*?)`/g, "$1")
    .trim();
}

function bulletsAfterHeading(markdown, heading) {
  const lines = (markdown || "").split("\n");
  const start = lines.findIndex((line) => line.trim().toLowerCase() === heading.toLowerCase());
  if (start < 0) return [];
  const bullets = [];
  for (const line of lines.slice(start + 1)) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    if (/^(Questions:|Quick worksheet:|Quick retained-capital read:|Stress question:|Rule:|Most important bias risk:)/i.test(trimmed)) break;
    if (trimmed.startsWith("- ")) bullets.push(trimmed.slice(2).trim());
    else if (bullets.length) break;
  }
  return bullets;
}

function bindScreeningReportEvents(report) {
  const reportForm = content.querySelector("#report-form");
  reportForm.addEventListener("submit", saveReport);
  bindCompletionPreviewTracking(reportForm);
  bindCompletionPreviewButton();
  content.querySelector("#source-import-button").addEventListener("click", createReportSource);
  content.querySelector("#source-add-button").addEventListener("click", () => openSourceDialog());
  content.querySelectorAll("[data-edit-source]").forEach((button) => {
    button.addEventListener("click", () => openSourceDialog(Number(button.dataset.editSource)));
  });
  content.querySelectorAll("[data-delete-source]").forEach((button) => {
    button.addEventListener("click", () => openSourceDeleteDialog(Number(button.dataset.deleteSource)));
  });
  content.querySelectorAll("[data-close-source-dialog]").forEach((button) => {
    button.addEventListener("click", () => content.querySelector("#source-dialog").close());
  });
  content.querySelector("#source-dialog").addEventListener("click", (event) => {
    if (event.target === event.currentTarget) event.currentTarget.close();
  });
  content.querySelectorAll("[data-close-source-delete]").forEach((button) => {
    button.addEventListener("click", () => content.querySelector("#source-delete-dialog").close());
  });
  content.querySelector("#source-delete-dialog").addEventListener("click", (event) => {
    if (event.target === event.currentTarget) event.currentTarget.close();
  });
  content.querySelector("#source-delete-confirm").addEventListener("click", confirmDeleteReportSource);
  content.querySelectorAll("[data-company-return]").forEach((button) => {
    button.addEventListener("click", () => openCompany(Number(button.dataset.companyReturn)));
  });
  bindDeleteReportButtons();
  content.querySelectorAll("[data-source-field]").forEach((button) => {
    button.addEventListener("click", () => openFieldPopover(button.dataset.sourceField, button.dataset.fieldLabel, "sources"));
  });
  content.querySelectorAll("[data-apply-section-sources]").forEach((button) => {
    button.addEventListener("click", () => applySectionSources(button.dataset.applySectionSources));
  });
  content.querySelectorAll("[data-note-field]").forEach((button) => {
    button.addEventListener("click", () => openFieldPopover(button.dataset.noteField, button.dataset.fieldLabel, "notes"));
  });
  const finalField = finalDecisionField(report.template.schema || { sections: [] });
  if (finalField) {
    content.querySelectorAll(`[data-field-id="${CSS.escape(finalField.id)}"]`).forEach((input) => {
      input.addEventListener("change", () => {
        if (input.type === "radio" && !input.checked) {
          updateFinalDecision("", "Draft");
          return;
        }
        const decision = normalizeFinalDecision(input.value);
        updateFinalDecision(decision, resultValueForDecisionOption(input.value) || "Draft");
      });
    });
  }
  updateDecisionPanels(finalDecisionFromReport(report, report.template.schema || { sections: [] }));
  content.querySelectorAll("[data-review-control]").forEach((control) => {
    control.querySelectorAll("[data-review-mode], [data-review-value]").forEach((input) => {
      input.addEventListener("input", () => syncReviewDateFromControl(control));
      input.addEventListener("change", () => syncReviewDateFromControl(control));
    });
  });
  content.querySelectorAll("[data-section-note]").forEach((textarea) => {
    textarea.addEventListener("input", () => {
      state.fieldNotes[textarea.dataset.sectionNote] = textarea.value;
      textarea.closest("details").querySelector("summary").classList.toggle("has-note", Boolean(textarea.value.trim()));
      refreshReportVisibilityContainers();
    });
  });
  content.querySelectorAll("[data-money-input]").forEach((input) => {
    input.addEventListener("input", () => enforceMoneyRange(input));
    input.addEventListener("blur", () => {
      if (input.value.trim() && !input.value.trim().startsWith("$")) input.value = `$${input.value.trim()}`;
    });
  });
  content.querySelectorAll("[data-field-id]").forEach((input) => {
    const refresh = () => syncRenderedFieldState(input.dataset.fieldId);
    input.addEventListener("input", refresh);
    input.addEventListener("change", refresh);
  });
  setupAutosizeTextareas();
  content.querySelectorAll(".result-spectrum input[type='radio']").forEach((input) => {
    input.addEventListener("dblclick", (event) => {
      if (input.disabled) return;
      event.preventDefault();
      input.checked = false;
      input.dispatchEvent(new Event("change", { bubbles: true }));
    });
  });
  content.querySelectorAll(".result-spectrum span").forEach((span) => {
    span.addEventListener("dblclick", (event) => {
      event.preventDefault();
      const input = span.previousElementSibling;
      if (input?.matches("input[type='radio']")) {
        if (input.disabled) return;
        input.checked = false;
        input.dispatchEvent(new Event("change", { bubbles: true }));
      }
    });
  });
  content.querySelectorAll(".destination-panel").forEach((panel) => {
    panel.addEventListener("toggle", () => {
      if (panel.classList.contains("locked") && panel.open) {
        panel.open = false;
        return;
      }
      if (!panel.open) return;
      content.querySelectorAll(".destination-panel").forEach((other) => {
        if (other !== panel) other.open = false;
      });
    });
  });
  bindPreviewButtons();
  updateReportVisibilityUI();
}

function setupAutosizeTextareas() {
  content.querySelectorAll("[data-autosize-textarea]").forEach((textarea) => {
    autosizeTextarea(textarea);
    textarea.addEventListener("input", () => autosizeTextarea(textarea));
  });
}

function autosizeTextarea(textarea) {
  textarea.style.height = "auto";
  textarea.style.height = `${Math.max(textarea.scrollHeight, 42)}px`;
}

function fieldPopoverMarkup() {
  return `<dialog id="field-popover" class="floating-box"></dialog>`;
}

function sourceDialogIsLinkOnly(root) {
  const url = root.querySelector("[name='url']")?.value.trim() || "";
  const documentId = root.querySelector("[name='document_id']")?.value.trim() || "";
  const fileInput = root.querySelector("[name='file']");
  return Boolean(url && !documentId && !fileInput?.files?.[0]);
}

function syncSourceDialogState() {
  const root = content.querySelector("#source-import-form");
  if (!root) return;
  const panel = root.querySelector("#source-link-only-panel");
  if (!panel) return;
  const linkOnly = sourceDialogIsLinkOnly(root);
  panel.classList.toggle("hidden", !linkOnly);
}

function openSourceDialog(sourceId = null) {
  const dialog = content.querySelector("#source-dialog");
  const root = content.querySelector("#source-import-form");
  const source = sourceId ? editableReportSources(state.currentReport).find((item) => Number(item.id) === Number(sourceId)) : null;
  root.querySelectorAll("input, textarea, select").forEach((input) => {
    if (input.type === "file") input.value = "";
    else if (input.type === "checkbox") input.checked = false;
    else input.value = "";
  });
  root.querySelector("[name='report_id']").value = state.currentReport.id;
  root.querySelector("[name='id']").value = source?.id || "";
  root.querySelector("[name='document_id']").value = source?.document_id || "";
  root.querySelector("[name='title']").value = source?.title || "";
  root.querySelector("[name='source_type']").value = source?.source_type || SOURCE_TYPES[0];
  root.querySelector("[name='evidence_grade']").value = source?.evidence_grade || "";
  root.querySelector("[name='confidence']").value = source?.confidence || "";
  root.querySelector("[name='url']").value = source?.url || "";
  root.querySelector("[name='citation']").value = source?.citation || "";
  root.querySelector("[name='tags']").value = (source?.tags || []).join(", ");
  root.querySelector("[name='notes']").value = source?.notes || "";
  root.querySelector("[name='snapshot_guidance_acknowledged']").checked = Boolean(source?.snapshot_guidance_acknowledged);
  root.querySelector("[name='link_only_reason']").value = source?.link_only_reason || "";
  content.querySelector("#source-dialog-title").textContent = source ? "Edit Source" : "Add Source";
  const urlInput = root.querySelector("[name='url']");
  const fileInput = root.querySelector("[name='file']");
  if (urlInput) urlInput.oninput = syncSourceDialogState;
  if (fileInput) fileInput.onchange = syncSourceDialogState;
  syncSourceDialogState();
  dialog.showModal();
}

function openFieldPopover(fieldId, label, activeTab) {
  state.activeFieldId = fieldId;
  state.activeFieldLabel = label;
  const dialog = content.querySelector("#field-popover");
  const entry = state.fieldSources[fieldId] || { source_ids: [], citation: "" };
  const notesLabel = fieldNoteButtonLabel(fieldId);
  dialog.innerHTML = `
    <div class="floating-box-inner">
      <div class="modal-header">
        <div>
          <h3>${escapeHtml(label)}</h3>
          <p class="muted">Link evidence and preserve field-level notes.</p>
        </div>
        <button type="button" class="icon-button" data-close-popover>x</button>
      </div>
      <div class="tabs">
        <button type="button" class="tab ${activeTab === "sources" ? "active" : ""}" data-popover-tab="sources">Sources</button>
        <button type="button" class="tab ${activeTab === "notes" ? "active" : ""}" data-popover-tab="notes">${escapeHtml(notesLabel)}</button>
      </div>
      <div class="popover-pane ${activeTab === "sources" ? "" : "hidden"}" data-pane="sources">
        ${sourceSelectionList(entry)}
        <label>Citation or area <input id="field-citation-input" value="${escapeAttr(entry.citation || "")}" placeholder="p. 234, slide 18, paragraph 3" /></label>
      </div>
      <div class="popover-pane ${activeTab === "notes" ? "" : "hidden"}" data-pane="notes">
        <label>Coverage exception
          <select id="field-exception-input">
            ${FIELD_EXCEPTION_OPTIONS.map(([value, label]) => `
              <option value="${escapeAttr(value)}" ${fieldExceptionStatus(fieldId) === value ? "selected" : ""}>${escapeHtml(label)}</option>
            `).join("")}
          </select>
        </label>
        <p class="muted">Use an exception only after investigation. It counts as coverage only when this field also has a note and a source.</p>
        <p class="muted">${escapeHtml(fieldNoteRequirementHelp(fieldId))}</p>
        <label>${escapeHtml(notesLabel)} <textarea id="field-note-input" rows="6" placeholder="${escapeAttr(fieldNotePlaceholder(fieldId))}">${escapeHtml(state.fieldNotes[fieldId] || "")}</textarea></label>
      </div>
      <div class="modal-actions">
        <button type="button" class="secondary" data-close-popover>Cancel</button>
        <button type="button" class="primary" data-save-popover>Save</button>
      </div>
    </div>
  `;
  dialog.querySelectorAll("[data-popover-tab]").forEach((button) => {
    button.addEventListener("click", () => {
      dialog.querySelectorAll("[data-popover-tab]").forEach((tab) => tab.classList.toggle("active", tab === button));
      dialog.querySelectorAll("[data-pane]").forEach((pane) => pane.classList.toggle("hidden", pane.dataset.pane !== button.dataset.popoverTab));
    });
  });
  dialog.querySelectorAll("[data-close-popover]").forEach((button) => button.addEventListener("click", () => dialog.close()));
  dialog.querySelector("[data-save-popover]").addEventListener("click", saveFieldPopover);
  dialog.addEventListener("click", closePopoverOnBackdropClick);
  dialog.showModal();
}

function closePopoverOnBackdropClick(event) {
  if (event.target === event.currentTarget) event.currentTarget.close();
}

function sourceSelectionGroupMarkup(title, description, sources, selected) {
  return `
    <div class="source-picker-group">
      <div class="source-picker-heading">
        <strong>${escapeHtml(title)}</strong>
        ${description ? `<small>${escapeHtml(description)}</small>` : ""}
      </div>
      ${sources.length ? sources.map((source) => {
        const detailBits = [
          sourceStageContext(source),
          source.source_type || "Source",
          evidenceGradeLabel(source.evidence_grade || "U"),
          source.confidence || "No confidence",
          sourceReusabilityLabel(source),
        ].filter(Boolean);
        return `
          <label class="source-picker-row">
            <input type="checkbox" value="${source.id}" ${selected.has(String(source.id)) ? "checked" : ""} />
            <span>
              <strong>${escapeHtml(source.title)}</strong>
              <small>${escapeHtml(detailBits.join(" · "))}</small>
              ${source.reusability_reason ? `<small>${escapeHtml(source.reusability_reason)}</small>` : ""}
              ${source.capture_state === "link_only" && source.link_only_reason ? `<small>Why link-only: ${escapeHtml(source.link_only_reason)}</small>` : ""}
            </span>
          </label>
        `;
      }).join("") : `<div class="empty-state">No sources in this group yet.</div>`}
    </div>
  `;
}

function sourceSelectionList(entry) {
  const groups = reportSourceGroups(state.currentReport || {});
  if (!groups.allAvailableSources.length) return `<div class="empty-state">Import sources in the Sources section first.</div>`;
  const selected = new Set((entry.source_ids || []).map(String));
  return `
    <div class="source-picker">
      ${sourceSelectionGroupMarkup("This Report’s Sources", "Sources created in this report.", groups.reportSources, selected)}
      ${sourceSelectionGroupMarkup("Suggested Company Sources", "Prior-stage cited sources ranked first for reuse.", groups.suggestedSources, selected)}
      ${sourceSelectionGroupMarkup("All Company Sources", "Remaining company-library sources available for direct citation.", groups.remainingCompanySources, selected)}
    </div>
  `;
}

function saveFieldPopover() {
  const dialog = content.querySelector("#field-popover");
  const fieldId = state.activeFieldId;
  const selected = [...dialog.querySelectorAll(".source-picker input:checked")].map((input) => Number(input.value));
  state.fieldSources[fieldId] = {
    source_ids: selected,
    citation: dialog.querySelector("#field-citation-input")?.value || "",
  };
  const noteValue = dialog.querySelector("#field-note-input")?.value || "";
  if (noteValue.trim()) state.fieldNotes[fieldId] = noteValue;
  else delete state.fieldNotes[fieldId];
  const exceptionStatus = dialog.querySelector("#field-exception-input")?.value || "";
  if (exceptionStatus) state.fieldExceptions[fieldId] = exceptionStatus;
  else delete state.fieldExceptions[fieldId];
  dialog.close();
  clearCompletionPreview();
  updateFieldToolButtons(fieldId);
  syncRenderedFieldState(fieldId);
}

function applySectionSources(sectionId) {
  const sectionKey = `section:${sectionId}`;
  const entry = state.fieldSources[sectionKey] || { source_ids: [], citation: "" };
  if (!(entry.source_ids || []).length) {
    status("Choose section sources first, then apply them to the section.", true);
    return;
  }
  const section = [...content.querySelectorAll("[data-section-id]")].find((item) => item.dataset.sectionId === sectionId);
  if (!section) return;
  const fieldIds = new Set();
  section.querySelectorAll("[data-field-id]").forEach((input) => fieldIds.add(input.dataset.fieldId));
  section.querySelectorAll("[data-source-field]").forEach((button) => {
    if (button.dataset.sourceField && button.dataset.sourceField !== sectionKey) fieldIds.add(button.dataset.sourceField);
  });
  fieldIds.forEach((fieldId) => {
    state.fieldSources[fieldId] = {
      source_ids: [...entry.source_ids],
      citation: entry.citation || "",
    };
    updateFieldToolButtons(fieldId);
    syncRenderedFieldState(fieldId);
  });
  clearCompletionPreview();
  refreshReportVisibilityContainers();
  status("Section sources applied to every answer in this section.");
}

function updateFieldToolButtons(fieldId) {
  content.querySelectorAll(`[data-source-field="${CSS.escape(fieldId)}"]`).forEach((button) => {
    const prefix = String(fieldId).startsWith("section:") ? "Section Sources" : "Sources";
    button.textContent = `${prefix} ${fieldSourceCount(fieldId)}`;
  });
  content.querySelectorAll(`[data-note-field="${CSS.escape(fieldId)}"]`).forEach((button) => {
    button.classList.toggle("has-note", fieldHasNote(fieldId) || fieldHasException(fieldId));
  });
}

async function createReportSource(event) {
  event.preventDefault();
  const root = content.querySelector("#source-import-form");
  const sourceId = root.querySelector("[name='id']").value;
  if (sourceDialogIsLinkOnly(root)) {
    const acknowledged = root.querySelector("[name='snapshot_guidance_acknowledged']").checked;
    const reason = root.querySelector("[name='link_only_reason']").value.trim();
    if (!acknowledged) {
      status("Read the snapshot guidance and acknowledge it before saving a URL-only source.", true);
      return;
    }
    if (!reason) {
      status("Explain why this source is still link-only before saving it.", true);
      return;
    }
  }
  const formData = new FormData();
  root.querySelectorAll("input, textarea, select").forEach((input) => {
    if (input.type === "file") {
      if (input.files[0]) formData.append(input.name, input.files[0]);
    } else if (input.type === "checkbox") {
      formData.append(input.name, input.checked ? "true" : "false");
    } else {
      formData.append(input.name, input.value);
    }
  });
  try {
    await api(sourceId ? `/api/report-sources/${sourceId}` : "/api/report-sources", {
      method: sourceId ? "PATCH" : "POST",
      body: formData,
    });
    content.querySelector("#source-dialog").close();
    status(sourceId ? "Source updated." : "Source imported.");
    await openReport(state.currentReport.id);
  } catch (error) {
    status(error.message, true);
  }
}

async function deleteReportSource(sourceId) {
  try {
    await api(`/api/report-sources/${sourceId}`, { method: "DELETE" });
    status("Source deleted.");
    await openReport(state.currentReport.id);
  } catch (error) {
    status(error.message, true);
  }
}

async function deleteCompanySource(sourceId, companyId) {
  try {
    await api(`/api/report-sources/${sourceId}`, { method: "DELETE" });
    await openCompany(companyId);
    status("Source deleted.");
  } catch (error) {
    status(error.message, true);
  }
}

function openSourceDeleteDialog(sourceId) {
  const source = editableReportSources(state.currentReport).find((item) => Number(item.id) === Number(sourceId));
  state.pendingDeleteSourceId = sourceId;
  const dialog = content.querySelector("#source-delete-dialog");
  dialog.querySelector("#source-delete-message").textContent = `Delete ${source?.title || "this source"}? This removes it from the report and unlinks it from cited answers.`;
  dialog.showModal();
}

async function confirmDeleteReportSource() {
  const sourceId = state.pendingDeleteSourceId;
  if (!sourceId) return;
  content.querySelector("#source-delete-dialog").close();
  state.pendingDeleteSourceId = null;
  await deleteReportSource(sourceId);
}

function bindPreviewButtons() {
  content.querySelectorAll("[data-preview-document]").forEach((button) => {
    button.addEventListener("click", () => openDocumentPreview(Number(button.dataset.previewDocument)));
  });
  content.querySelectorAll("[data-close-document-preview]").forEach((button) => {
    button.addEventListener("click", () => content.querySelector("#document-preview-dialog")?.close());
  });
  content.querySelector("#document-preview-dialog")?.addEventListener("click", (event) => {
    if (event.target === event.currentTarget) event.currentTarget.close();
  });
}

function bindCompanyUploadDialog() {
  const dialog = content.querySelector("#document-upload-dialog");
  if (!dialog) return;
  content.querySelectorAll("[data-open-upload-dialog]").forEach((button) => {
    button.addEventListener("click", () => dialog.showModal());
  });
  content.querySelectorAll("[data-close-upload-dialog]").forEach((button) => {
    button.addEventListener("click", () => dialog.close());
  });
  dialog.addEventListener("click", (event) => {
    if (event.target === event.currentTarget) event.currentTarget.close();
  });
}

function bindDetailToggleButtons() {
  content.querySelectorAll("[data-detail-toggle]").forEach((button) => {
    button.addEventListener("click", () => {
      const panel = button.closest(".panel");
      const target = panel?.querySelector("[data-detail-region]");
      if (!target) return;
      const expanded = button.getAttribute("aria-expanded") === "true";
      const nextExpanded = !expanded;
      button.setAttribute("aria-expanded", nextExpanded ? "true" : "false");
      button.textContent = nextExpanded
        ? button.dataset.collapseLabel || "Less Detail"
        : button.dataset.expandLabel || "More Detail";
      target.classList.toggle("hidden", !nextExpanded);
    });
  });
}

function bindDeleteReportButtons() {
  content.querySelectorAll("[data-delete-report]").forEach((button) => {
    button.addEventListener("click", () => {
      deleteReport(
        Number(button.dataset.deleteReport),
        Number(button.dataset.companyId || state.currentReport?.company_id || state.currentCompany?.id || 0),
        button.dataset.reportTitle || "this report",
      );
    });
  });
}

async function deleteReport(reportId, companyId, reportTitle) {
  if (!reportId) return;
  if (!window.confirm(`Delete ${reportTitle}? Linked report sources and monitoring rules from this report will be removed. Uploaded documents stay in the company library.`)) return;
  try {
    const result = await api(`/api/reports/${reportId}`, { method: "DELETE" });
    await refreshBootstrap();
    status("Report deleted.");
    state.currentReport = null;
    const nextCompanyId = Number(result.company?.id || companyId || state.currentCompany?.id || 0);
    if (nextCompanyId) {
      await openCompany(nextCompanyId);
      return;
    }
    renderView(state.view);
  } catch (error) {
    status(error.message, true);
  }
}

function openDocumentPreview(documentId) {
  const item = findDocumentPreviewItem(documentId);
  if (!item) {
    status("Preview unavailable for this document.", true);
    return;
  }
  const dialog = content.querySelector("#document-preview-dialog");
  if (!dialog) return;
  dialog.querySelector("#document-preview-title").textContent = item.title;
  const meta = [
    item.mimeType || "",
    item.normalizedFormat || item.normalizedStatus || "",
    item.normalizedMethod || "",
  ].filter(Boolean).join(" · ");
  dialog.querySelector("#document-preview-meta").textContent = meta || "LLM-ready source preview.";
  dialog.querySelector("#document-preview-text").textContent = item.preview || item.notes || "No normalized preview available.";
  dialog.querySelector("#document-preview-actions").innerHTML = `
    <button type="button" class="secondary" data-close-document-preview>Close</button>
    ${item.normalizedAvailable ? `<a class="small-button" href="/api/documents/${item.id}/normalized" target="_blank" rel="noreferrer">Open LLM View</a>` : ""}
    <a class="small-button" href="/api/documents/${item.id}/download">Download Original</a>
  `;
  dialog.querySelectorAll("[data-close-document-preview]").forEach((button) => {
    button.addEventListener("click", () => dialog.close());
  });
  dialog.showModal();
}

function findDocumentPreviewItem(documentId) {
  const docs = [
    ...(state.currentCompany?.documents || []),
    ...(state.currentReport?.documents || []),
  ];
  for (const doc of docs) {
    if (Number(doc.id) === Number(documentId)) {
      return {
        id: Number(doc.id),
        title: doc.original_name,
        mimeType: doc.mime_type,
        normalizedStatus: doc.normalized_status,
        normalizedFormat: doc.normalized_format,
        normalizedMethod: doc.normalized_method,
        preview: doc.normalized_preview,
        notes: doc.normalized_notes,
        normalizedAvailable: Boolean(doc.normalized_available),
      };
    }
  }
  const sources = availableSources(state.currentReport || {});
  for (const source of sources) {
    if (Number(source.document_id) === Number(documentId)) {
      return {
        id: Number(source.document_id),
        title: source.title || source.document_name || `Document ${documentId}`,
        mimeType: source.document_mime_type,
        normalizedStatus: source.normalized_status,
        normalizedFormat: source.normalized_format,
        normalizedMethod: source.normalized_method,
        preview: source.normalized_preview,
        notes: source.normalized_notes,
        normalizedAvailable: Boolean(source.normalized_available),
      };
    }
  }
  const companySources = state.currentCompany?.company_sources || [];
  for (const source of companySources) {
    if (Number(source.document_id) === Number(documentId)) {
      return {
        id: Number(source.document_id),
        title: source.title || source.document_name || `Document ${documentId}`,
        mimeType: source.document_mime_type,
        normalizedStatus: source.normalized_status,
        normalizedFormat: source.normalized_format,
        normalizedMethod: source.normalized_method,
        preview: source.normalized_preview,
        notes: source.normalized_notes,
        normalizedAvailable: Boolean(source.normalized_available),
      };
    }
  }
  return null;
}

function updateFinalDecision(decision, resultValue) {
  const resultInput = content.querySelector("input[name='result']");
  if (resultInput) resultInput.value = resultValue;
  syncLinkedFinalDecision(decision);
  updateDecisionPanels(decision);
}

function syncReviewDateFromControl(control) {
  const hidden = content.querySelector("input[name='review_date']");
  if (!hidden) return;
  const mode = control.querySelector("[data-review-mode]")?.value || "date";
  const raw = control.querySelector("[data-review-value]")?.value.trim() || "";
  if (!raw) {
    hidden.value = "";
    return;
  }
  hidden.value = mode === "interval" && !/^in\s+/i.test(raw) ? `in ${raw}` : raw;
}

function syncLinkedFinalDecision(decision) {
  content.querySelectorAll("[data-linked-final-decision]").forEach((input) => {
    input.checked = Boolean(decision && input.dataset.linkedFinalDecision === decision);
  });
}

function updateDecisionPanels(decision) {
  content.querySelectorAll("[data-decision-panel]").forEach((panel) => {
    const keys = String(panel.dataset.decisionPanel || "")
      .split("|")
      .map((item) => item.trim())
      .filter(Boolean);
    const active = Boolean(decision && keys.includes(decision));
    panel.classList.toggle("locked", Boolean(decision && !active));
    panel.open = Boolean(active);
    panel.querySelectorAll("input, textarea, select, button").forEach((control) => {
      control.disabled = Boolean(decision && !active);
    });
  });
}

function enforceMoneyRange(input) {
  let value = input.value.replace(/[^0-9.,$%\\-\\sTtBbMmKk]/g, "");
  const letters = value.match(/[TtBbMmKk]/g) || [];
  if (letters.length > 1) {
    const first = letters[0];
    value = value.replace(/[TtBbMmKk]/g, "");
    value += first.toUpperCase();
  }
  input.value = value;
}

function sourceEvidenceOptions(selected) {
  const options = [["", ""]].concat(EVIDENCE_GRADES);
  return options.map(([value, label]) => {
    const text = value ? `${value} - ${label}` : "";
    return `<option value="${value}" ${selected === value ? "selected" : ""}>${escapeHtml(text)}</option>`;
  }).join("");
}

function evidenceGradeLabel(value) {
  const grade = String(value || "").trim();
  const found = EVIDENCE_GRADES.find(([code]) => code === grade);
  if (!grade) return "";
  return found ? `${found[0]} - ${found[1]}` : `${grade} - Ungraded source`;
}

function confidenceOptions(selected) {
  return ["", "High", "Medium", "Low"].map((value) => `<option value="${value}" ${selected === value ? "selected" : ""}>${value || ""}</option>`).join("");
}

function resultOptions(selected) {
  const values = ["Draft", ...state.bootstrap.report_actions];
  return values.map((value) => `<option value="${escapeAttr(value)}" ${selected === value ? "selected" : ""}>${escapeHtml(value)}</option>`).join("");
}

function generateRuleKey() {
  if (window.crypto?.randomUUID) return `rule-${window.crypto.randomUUID()}`;
  return `rule-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

function objectiveRuleRow(rule) {
  return `
    <div class="objective-rule" data-objective-rule>
      <input type="hidden" name="rule_key" value="${escapeAttr(rule.rule_key || generateRuleKey())}" />
      <label>Metric <input name="metric_name" value="${escapeAttr(rule.metric_name || rule.metric || "")}" placeholder="Stock price" /></label>
      <label>Check <select name="comparator">${comparatorOptions(rule.comparator || "<=")}</select></label>
      <label>Threshold <input name="threshold_value" type="number" step="any" value="${escapeAttr(rule.threshold_value ?? "")}" /></label>
      <label>Source <input name="source" value="${escapeAttr(rule.source || "")}" placeholder="Manual or provider" /></label>
    </div>
  `;
}

function comparatorOptions(selected) {
  return ["<=", "<", ">=", ">", "="].map((item) => `<option value="${item}" ${selected === item ? "selected" : ""}>${item}</option>`).join("");
}

async function renderMonitoring() {
  const data = await api("/api/monitoring");
  content.innerHTML = `
    <section class="panel">
      <div class="panel-header">
        <div>
          <h3>Objective Rules</h3>
          <p class="muted">Update runtime values and notes here. Report-owned rule structure stays in the report editor.</p>
        </div>
      </div>
      <div class="panel-body">
        ${monitoringTable(data.rules)}
      </div>
    </section>
  `;
  content.querySelectorAll(".monitoring-update").forEach((form) => {
    form.addEventListener("submit", updateMonitoringRule);
  });
}

function monitoringTable(rules) {
  if (!rules.length) return `<div class="empty-state">No monitoring rules have been created from reports yet.</div>`;
  return `
    <div class="table-wrap">
      <table>
        <thead>
          <tr><th>Company</th><th>Metric</th><th>Rule</th><th>Runtime Updates</th><th>Status</th><th>Source</th><th>Last Checked</th></tr>
        </thead>
        <tbody>
          ${rules.map((rule) => `
            <tr>
              <td><strong>${escapeHtml(rule.ticker)}</strong><br><span class="muted">${escapeHtml(rule.company_name)}</span></td>
              <td>${escapeHtml(rule.metric_name)}</td>
              <td>${escapeHtml(rule.comparator)} ${escapeHtml(rule.threshold_value ?? "")} ${escapeHtml(rule.unit || "")}</td>
              <td>
                <form class="monitoring-update" data-rule-id="${rule.id}">
                  <input name="current_value" type="number" step="any" value="${escapeAttr(rule.current_value ?? "")}" />
                  <textarea name="notes" rows="2" placeholder="Runtime note">${escapeHtml(rule.notes || "")}</textarea>
                  <button class="small-button">Save</button>
                </form>
              </td>
              <td><span class="pill ${rule.triggered ? "green" : ""}">${rule.triggered ? "Triggered" : "Waiting"}</span></td>
              <td>${escapeHtml(rule.source || "")}</td>
              <td>${formatDate(rule.last_checked_at)}</td>
            </tr>
          `).join("")}
        </tbody>
      </table>
    </div>
  `;
}

async function renderTemplates(root = content) {
  if (!root) return;
  const templates = await loadTemplateLibrary();
  const selectedSummary = state.selectedTemplateId === null
    ? null
    : (templates.find((template) => template.id === state.selectedTemplateId) || templates[0] || null);
  const selected = selectedSummary ? await loadTemplateDetail(selectedSummary.id) : null;
  state.selectedTemplateId = selected?.id || null;
  state.selectedTemplateStageId = selected?.stage_id || state.selectedTemplateStageId || templates[0]?.stage_id || null;
  const selectedStageId = selected?.stage_id || state.selectedTemplateStageId || state.bootstrap.stages[0]?.id || "";
  const stageOptions = state.bootstrap.stages.map((stage) => {
    const checked = Number(selectedStageId) === stage.id ? "selected" : "";
    return `<option value="${stage.id}" ${checked}>${escapeHtml(stage.name)}</option>`;
  }).join("");
  const stageField = selected
    ? `
        <input type="hidden" name="stage_id" value="${escapeAttr(selected.stage_id)}" />
        <label>Stage <input value="${escapeAttr(selected.stage_name)}" disabled /></label>
      `
    : `<label>Stage <select name="stage_id" required>${stageOptions}</select></label>`;
  root.innerHTML = `
    <section class="split">
      <aside class="panel">
        <div class="panel-header">
          <div>
            <h3>Template Library</h3>
            <p class="muted">Saving creates a new active version for future reports. Existing reports stay pinned to their current template snapshot.</p>
          </div>
        </div>
        <div class="panel-body grid">
          <button class="secondary" id="new-template">New Template</button>
          ${templates.map((template) => `
            <div class="template-list-row">
              <button class="tab ${template.id === selected?.id ? "active" : ""}" data-template-id="${template.id}">
                ${escapeHtml(template.stage_name)}: ${escapeHtml(template.name)}
              </button>
              <button class="small-button danger" type="button" data-delete-template="${template.id}">Delete</button>
            </div>
          `).join("")}
        </div>
      </aside>
      <section class="panel">
        <form id="template-form">
          <div class="panel-header">
            <div>
              <h3>${selected ? escapeHtml(selected.name) : "New Template"}</h3>
              <p class="muted">${selected?.schema?.field_count || 0} fields currently detected.${selected ? " Saving will create the next active version for this stage." : ""}</p>
            </div>
            <button class="primary">Save Template</button>
          </div>
          <div class="panel-body grid">
            <input type="hidden" name="id" value="${selected?.id || ""}" />
            <div class="form-grid">
              ${stageField}
              <label>Name <input name="name" value="${escapeAttr(selected?.name || "")}" required /></label>
            </div>
            <label>Description <input name="description" value="${escapeAttr(selected?.description || "")}" /></label>
            <label>Markdown <textarea class="template-editor" name="markdown" required>${escapeHtml(selected?.markdown || "# New Template\n\n## Section\n\n- Question:\n\n**Answer**:\n\n**Final Decision**: Proceed to Next Step / Watchlist / Archive\n")}</textarea></label>
          </div>
        </form>
      </section>
    </section>
  `;
  root.querySelectorAll("[data-template-id]").forEach((button) => {
    button.addEventListener("click", () => {
      state.selectedTemplateId = Number(button.dataset.templateId);
      void renderTemplates(root);
    });
  });
  root.querySelectorAll("[data-delete-template]").forEach((button) => {
    button.addEventListener("click", () => deleteTemplate(Number(button.dataset.deleteTemplate)));
  });
  root.querySelector("#new-template").addEventListener("click", () => {
    state.selectedTemplateStageId = selected?.stage_id || state.selectedTemplateStageId || state.bootstrap.stages[0]?.id || null;
    state.selectedTemplateId = null;
    void renderTemplates(root);
  });
  root.querySelector("#template-form").addEventListener("submit", saveTemplate);
}

async function deleteTemplate(templateId) {
  const templates = await loadTemplateLibrary();
  const template = templates.find((item) => Number(item.id) === Number(templateId));
  if (!template) return;
  if (!window.confirm(`Delete ${template.name}? Existing reports keep their historical template copy.`)) return;
  try {
    await api(`/api/templates/${templateId}`, { method: "DELETE" });
    if (state.selectedTemplateId === templateId) state.selectedTemplateId = undefined;
    state.templateLibrary = null;
    status("Template deleted.");
    renderTemplates();
  } catch (error) {
    status(error.message, true);
  }
}

async function createCompanyFromDialog(event) {
  event.preventDefault();
  const dialog = document.querySelector("#company-dialog");
  const form = event.currentTarget;
  await createCompany(Object.fromEntries(new FormData(form).entries()));
  form.reset();
  dialog.close();
}

async function createCompanyInline(event) {
  event.preventDefault();
  const form = event.currentTarget;
  await createCompany(Object.fromEntries(new FormData(form).entries()));
  form.reset();
}

async function createCompany(payload) {
  try {
    const result = await api("/api/companies", { method: "POST", body: JSON.stringify(payload) });
    await refreshBootstrap();
    status(`${result.company.ticker} added to All Companies.`);
    if (state.view !== "dashboard") renderView(state.view);
  } catch (error) {
    status(error.message, true);
  }
}

function openCompanyDialog() {
  document.querySelector("#company-dialog").showModal();
}

async function createReportForCompany(event) {
  event.preventDefault();
  const payload = Object.fromEntries(new FormData(event.currentTarget).entries());
  payload.company_id = state.currentCompany.id;
  try {
    const result = await api("/api/reports", { method: "POST", body: JSON.stringify(payload) });
    await refreshBootstrap();
    await openReport(result.report.id);
  } catch (error) {
    status(error.message, true);
  }
}

async function uploadDocument(event) {
  event.preventDefault();
  const form = event.currentTarget;
  try {
    await api("/api/documents", { method: "POST", body: new FormData(form) });
    content.querySelector("#document-upload-dialog")?.close();
    status("Document uploaded.");
    await openCompany(state.currentCompany.id);
  } catch (error) {
    status(error.message, true);
  }
}

function buildReportPayload(form, { finalize = false } = {}) {
  const responses = {};
  const metrics = {};
  const radioFields = new Map();
  form.querySelectorAll("[data-field-id]").forEach((input) => {
    const id = input.dataset.fieldId;
    const kind = input.dataset.fieldKind;
    if (input.type === "radio") {
      radioFields.set(id, kind);
      if (!input.checked) return;
    }
    const value = input.type === "checkbox" ? (input.checked ? "true" : "") : input.value;
    if (kind === "metric" || kind === "number") {
      metrics[id] = value;
    } else {
      responses[id] = value;
    }
  });
  radioFields.forEach((kind, id) => {
    if (Object.prototype.hasOwnProperty.call(responses, id) || Object.prototype.hasOwnProperty.call(metrics, id)) return;
    if (kind === "metric" || kind === "number") metrics[id] = "";
    else responses[id] = "";
  });
  const sectionRatings = {};
  form.querySelectorAll("[data-section-id]").forEach((section) => {
    const sectionId = section.dataset.sectionId;
    const checked = section.querySelector(".rating-strip input:checked");
    if (checked) sectionRatings[sectionId] = Number(checked.value);
  });
  const dataQuality = {};
  form.querySelectorAll("[data-data-quality]").forEach((select) => {
    if (select.value) dataQuality[select.dataset.dataQuality] = Number(select.value);
  });
  const formValue = (name) => form.elements[name]?.value || "";
  const payload = {
    expected_revision: state.currentReport.revision,
    finalize,
    title: formValue("title"),
    report_month: formValue("report_month"),
    result: formValue("result"),
    summary: formValue("summary"),
    watchlist_conditions: formValue("watchlist_conditions"),
    watchlist_subjective_rules: formValue("watchlist_subjective_rules"),
    archive_red_flags: formValue("archive_red_flags"),
    next_action: formValue("next_action"),
    review_date: formValue("review_date"),
    responses,
    metrics,
    section_ratings: sectionRatings,
    data_quality: dataQuality,
    field_sources: state.fieldSources,
    field_notes: state.fieldNotes,
    field_exceptions: state.fieldExceptions,
    watchlist_objective_rules: collectObjectiveRules(form),
  };
  return payload;
}

function clearCompletionPreview() {
  if (!state.completionPreview) return;
  state.completionPreview = null;
  renderReportQualityPanel();
}

function bindCompletionPreviewTracking(form) {
  const clear = () => clearCompletionPreview();
  form.addEventListener("input", clear);
  form.addEventListener("change", clear);
}

function bindCompletionPreviewButton() {
  content.querySelectorAll("[data-refresh-completion-preview]").forEach((button) => {
    button.addEventListener("click", refreshCompletionPreview);
  });
}

async function refreshCompletionPreview() {
  const form = content.querySelector("#report-form");
  if (!form || !state.currentReport?.id) return;
  try {
    const result = await api(`/api/reports/${state.currentReport.id}/preview`, {
      method: "POST",
      body: JSON.stringify(buildReportPayload(form)),
    });
    state.completionPreview = {
      reportId: state.currentReport.id,
      completion: result.completion || {},
    };
    renderReportQualityPanel();
    status("Completion preview refreshed.");
  } catch (error) {
    status(error.message, true);
  }
}

async function saveReport(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const finalize = event.submitter?.dataset.finalizeReport === "1";
  const payload = buildReportPayload(form, { finalize });
  try {
    const result = await api(`/api/reports/${state.currentReport.id}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
    state.completionPreview = null;
    state.currentReport = result.report;
    await refreshBootstrap();
    status(finalize ? "Report finalized and workflow position updated." : "Draft saved.");
    renderReportEditor(result.report);
  } catch (error) {
    if (error.status === 409 && error.payload?.code === "report_revision_conflict") {
      const updatedAt = error.payload.updated_at ? ` Latest save: ${formatDate(error.payload.updated_at)}.` : "";
      const reload = window.confirm(
        `This report was changed elsewhere after you opened it.${updatedAt}\n\nPress OK to reload the latest version and discard these unsaved edits, or Cancel to keep this form open.`
      );
      if (reload) {
        await openReport(state.currentReport.id);
        status("Reloaded the latest report version.");
      } else {
        status("Report changed since you opened it. Reload the latest version before retrying save.", true);
      }
      return;
    }
    if (error.status === 422 && error.payload?.code === "report_completion_blocked") {
      const completion = error.payload.completion || {};
      const message = [
        error.message,
        completion.missing_field_ids?.length ? `${completion.missing_field_ids.length} fields still uncovered.` : "",
        completion.missing_source_field_ids?.length ? `${completion.missing_source_field_ids.length} covered fields still need sources.` : "",
        completion.blocked_source_field_ids?.length ? `${completion.blocked_source_field_ids.length} covered fields still cite blocked sources.` : "",
        completion.missing_required_note_ids?.length ? `${completion.missing_required_note_ids.length} covered fields still need required notes.` : "",
        completion.exception_missing_note_ids?.length ? `${completion.exception_missing_note_ids.length} exceptions still need notes.` : "",
        ...(completion.decision_requirements || []),
      ].filter(Boolean).join(" ");
      status(message, true);
      return;
    }
    status(error.message, true);
  }
}

function collectObjectiveRules(root) {
  return [...root.querySelectorAll("[data-objective-rule]")].map((row) => {
    return {
      rule_key: row.querySelector("[name='rule_key']").value,
      metric_name: row.querySelector("[name='metric_name']").value,
      comparator: row.querySelector("[name='comparator']").value,
      threshold_value: row.querySelector("[name='threshold_value']").value,
      source: row.querySelector("[name='source']").value,
    };
  }).filter((rule) => rule.metric_name);
}

async function updateMonitoringRule(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const payload = Object.fromEntries(new FormData(form).entries());
  try {
    await api(`/api/monitoring-rules/${form.dataset.ruleId}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
    await refreshBootstrap();
    if (state.currentCompany && state.view !== "monitoring") {
      await openCompany(state.currentCompany.id);
      return;
    }
    renderMonitoring();
  } catch (error) {
    status(error.message, true);
  }
}

async function saveTemplate(event) {
  event.preventDefault();
  const payload = Object.fromEntries(new FormData(event.currentTarget).entries());
  const path = payload.id ? `/api/templates/${payload.id}` : "/api/templates";
  const method = payload.id ? "PATCH" : "POST";
  try {
    const result = await api(path, { method, body: JSON.stringify(payload) });
    state.selectedTemplateId = result.template.id;
    state.selectedTemplateStageId = result.template.stage_id;
    state.templateLibrary = null;
    status("Template saved. Future reports will use the new active version.");
    renderTemplates();
  } catch (error) {
    status(error.message, true);
  }
}

function alertList(alerts) {
  return `
    <div class="grid">
      ${alerts.map((alert) => `
        <div>
          <strong>${escapeHtml(alert.ticker)} - ${escapeHtml(alert.metric_name)}</strong>
          <p class="muted">${escapeHtml(alert.current_value)} ${escapeHtml(alert.comparator)} ${escapeHtml(alert.threshold_value)} ${escapeHtml(alert.unit || "")}</p>
        </div>
      `).join("")}
    </div>
  `;
}

function status(message, isError = false) {
  statusEl.textContent = message;
  statusEl.classList.toggle("error", isError);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function escapeAttr(value) {
  return escapeHtml(value);
}

function slugify(value) {
  return String(value || "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 80) || "field";
}

function formatDate(value) {
  if (!value) return "";
  return new Date(value).toLocaleString();
}

function formatBytes(value) {
  const size = Number(value || 0);
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}
