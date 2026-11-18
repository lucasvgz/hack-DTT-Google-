/**
 * Tickmark — UI (vanilla JS, aucun build). Routeur hash + vues.
 * Vues : accueil → dossier client (upload) → analyse → revue (pointage) → synthèse → portail client.
 */
import { CONFIG } from "./config.js";
import { CLIENTS, CATEGORIES, SEVERITY } from "./data.js";
import { CATEGORY_ORDER } from "./diff-engine.js";
import * as store from "./store.js";
import * as api from "./api.js";
import { DEMO_BEFORE, DEMO_AFTER } from "./demo-docs.js";

/* =============================================================================
   Utilitaires
   ============================================================================= */
const $ = (s, root = document) => root.querySelector(s);
const $$ = (s, root = document) => [...root.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const clientById = (id) => CLIENTS.find((c) => c.id === id);
const fmtDate = (iso) => iso ? new Date(iso).toLocaleDateString("fr-FR", { day: "2-digit", month: "short", year: "numeric" }) : "—";
const fmtDateTime = (iso) => iso ? new Date(iso).toLocaleString("fr-FR", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }) : "—";
const fmtTime = (iso) => iso ? new Date(iso).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "—";
const fmtSize = (b) => b > 1048576 ? `${(b / 1048576).toFixed(1)} Mo` : `${Math.max(1, Math.round(b / 1024))} Ko`;
const shortHash = (h) => h ? `${h.slice(0, 10)}…${h.slice(-6)}` : "—";
const plural = (n, s, p = s + "s") => `${n} ${n > 1 ? p : s}`;
const catColor = (k) => CATEGORIES[k]?.color || "#888";
/** Rend les blancs visibles : · pour espace, ↵ pour retour ligne. */
const showWs = (s) => esc(s).replace(/ /g, '<span class="wsv">·</span>').replace(/\n/g, '<span class="wsv">↵</span>').replace(/\f/g, '<span class="wsv">⇟</span>');
/** Affiche une valeur d'écart : blancs visibles uniquement pour les écarts de mise en forme. */
const showVal = (d, v) => (d.category === "mise_en_forme" || /^\s+$/.test(v)) ? showWs(v) : esc(v).replace(/\n/g, " ↵ ").replace(/\f/g, " ⇟ ");
const compact = (s, n = 42) => { const t = s.replace(/\f/g, " ").replace(/\n/g, "↵").replace(/ {2,}/g, (m) => "·".repeat(m.length)); return t.length > n ? t.slice(0, n) + "…" : t; };

const I = {
  arrow: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14M13 6l6 6-6 6"/></svg>',
  back: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 12H5M11 18l-6-6 6-6"/></svg>',
  up: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="m18 15-6-6-6 6"/></svg>',
  down: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6"/></svg>',
  check: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>',
  x: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M18 6 6 18M6 6l12 12"/></svg>',
  upload: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 16V4M7 9l5-5 5 5M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3"/></svg>',
  lock: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/></svg>',
  shield: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3 4 6v6c0 5 3.5 8 8 9 4.5-1 8-4 8-9V6z"/><path d="m9 12 2 2 4-4"/></svg>',
  fp: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M12 11v3M8 11a4 4 0 0 1 8 0v1c0 3-1 6-3 8M5 14c0-4 0-9 7-9s7 5 7 9"/></svg>',
  eye: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/></svg>',
  send: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 2 11 13M22 2l-7 20-4-9-9-4z"/></svg>',
  print: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9V2h12v7M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/><rect x="6" y="14" width="12" height="8"/></svg>',
  dl: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 4v12M7 11l5 5 5-5M4 20h16"/></svg>',
  pen: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/></svg>',
};

/* =============================================================================
   État UI (mémoire uniquement — les fichiers bruts ne sont jamais persistés)
   ============================================================================= */
const ui = {
  role: (() => { try { return sessionStorage.getItem("tickmark.role") || "auditor"; } catch { return "auditor"; } })(),
  uploads: {},        // clientId -> { before, after } (avec buffer en mémoire)
  running: {},        // sessionId -> { steps: {key: status}, error }
  review: { filter: "all", activeId: null },
  clientEntity: "bnp",
};

function setRole(role) {
  ui.role = role;
  try { sessionStorage.setItem("tickmark.role", role); } catch { /* ignore */ }
  const target = role === "client" ? "#/client" : "#/";
  if (location.hash === target || (target === "#/" && !location.hash)) route(); else location.hash = target;
}

/* =============================================================================
   Shell : barre supérieure
   ============================================================================= */
function topbar(crumbs = []) {
  const secure = api.isRemote()
    ? `<span class="secure-pill" title="Flux chiffrés TLS vers ${esc(CONFIG.API_BASE_URL)}"><span class="dot"></span>Connecté · TLS</span>`
    : `<span class="secure-pill" title="Mode démo : extraction et comparaison exécutées dans le navigateur, aucune donnée transmise"><span class="dot"></span>Traitement local · 0 octet envoyé</span>`;
  return `
  <header class="topbar">
    <a class="brand" href="${ui.role === "client" ? "#/client" : "#/"}" aria-label="Accueil">
      <span class="wordmark">Deloitte<i></i></span>
      <span class="brand-sep"></span>
      <span class="product"><b>${esc(CONFIG.APP_NAME)}</b><span>${ui.role === "client" ? "Espace client" : esc(CONFIG.APP_TAGLINE)}</span></span>
    </a>
    <nav class="crumbs">${crumbs.map((c, i) => (i ? "<span>/</span>" : "") + (c.href ? `<a href="${c.href}">${esc(c.label)}</a>` : `<b>${esc(c.label)}</b>`)).join("")}</nav>
    <div class="spacer"></div>
    ${secure}
    <div class="seg" role="tablist" aria-label="Vue">
      <button class="${ui.role === "auditor" ? "on" : ""}" data-role="auditor">Auditeur</button>
      <button class="${ui.role === "client" ? "on" : ""}" data-role="client">Client</button>
    </div>
    <div class="avatar" title="${esc(store.userName())} — ${esc(CONFIG.USER.role)}">${esc(CONFIG.USER.initials)}</div>
  </header>`;
}

function mount(html, crumbs) {
  document.body.innerHTML = topbar(crumbs) + `<main id="view">${html}</main>`;
  $$(".seg button").forEach((b) => b.addEventListener("click", () => setRole(b.dataset.role)));
}

function toast(msg) {
  $(".toast")?.remove();
  const t = document.createElement("div");
  t.className = "toast";
  t.innerHTML = `<i></i>${esc(msg)}`;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 2600);
}

function modal(html, bind) {
  const o = document.createElement("div");
  o.className = "overlay";
  o.innerHTML = `<div class="modal" role="dialog" aria-modal="true">${html}</div>`;
  document.body.appendChild(o);
  const close = () => { o.remove(); document.removeEventListener("keydown", onKey); };
  const onKey = (e) => { if (e.key === "Escape") close(); };
  document.addEventListener("keydown", onKey);
  o.addEventListener("click", (e) => { if (e.target === o) close(); });
  $$("[data-close]", o).forEach((b) => b.addEventListener("click", close));
  bind?.(o, close);
  return close;
}

/* =============================================================================
   Statistiques
   ============================================================================= */
function stats(diffs) {
  const by = Object.fromEntries(CATEGORY_ORDER.map((k) => [k, { total: 0, pending: 0, confirmed: 0, dismissed: 0 }]));
  let pending = 0, confirmed = 0, dismissed = 0;
  for (const d of diffs) {
    const b = by[d.category] || (by[d.category] = { total: 0, pending: 0, confirmed: 0, dismissed: 0 });
    b.total++; b[d.status || "pending"]++;
    if (d.status === "confirmed") confirmed++; else if (d.status === "dismissed") dismissed++; else pending++;
  }
  return { total: diffs.length, pending, confirmed, dismissed, by };
}

/* =============================================================================
   Vue 1 — Accueil
   ============================================================================= */
function viewHome() {
  const sessions = store.allSessions();
  const inReview = sessions.filter((s) => s.status === "review").length;
  const treated = sessions.reduce((n, s) => n + (s.differences || []).filter((d) => d.status !== "pending").length, 0);
  const hour = new Date().getHours();
  const hello = hour < 18 ? "Bonjour" : "Bonsoir";
  const today = new Date().toLocaleDateString("fr-FR", { weekday: "long", day: "numeric", month: "long", year: "numeric" });

  mount(`
  <div class="page">
    <div class="home-head">
      <div>
        <div class="eyebrow">${esc(today)}</div>
        <h1 class="hello">${hello}, <em>${esc(CONFIG.USER.firstName)}</em>.</h1>
        <p class="lead">Sélectionnez un dossier client, déposez les deux versions du document : l'agent repère <b>tous</b> les écarts, les catégorise, et vous n'avez plus qu'à pointer.</p>
      </div>
      <div class="kpis">
        <div class="card kpi"><div class="v">${CLIENTS.length}</div><div class="l">Dossiers actifs</div></div>
        <div class="card kpi"><div class="v">${inReview}</div><div class="l">Pointages en cours</div></div>
        <div class="card kpi"><div class="v">${treated}</div><div class="l">Écarts traités</div></div>
      </div>
    </div>

    <div class="section-title">
      <h2>Mes dossiers d'audit</h2>
      <input class="search" id="q" type="search" placeholder="Rechercher un client…" aria-label="Rechercher un client">
    </div>
    <div class="folders" id="folders">
      ${CLIENTS.map((c) => {
        const last = store.sessionsFor(c.id)[0];
        const status = last ? statusPill(last.status) : '<span class="pill">Aucun pointage</span>';
        return `
        <a class="card folder" href="#/dossier/${c.id}" data-name="${esc(c.name.toLowerCase())}">
          <div class="folder-top">
            <div class="mono-logo" style="--hue:${c.hue}">${esc(c.short)}</div>
            <div><h3>${esc(c.name)}</h3><div class="sector">${esc(c.sector)} · ${esc(c.phase)}</div></div>
          </div>
          <div class="meta">
            <div><span>Mission</span><span>${esc(c.mission)}</span></div>
            <div><span>Document</span><span>${esc(c.doc.replace("Document d'enregistrement universel", "URD"))}</span></div>
            <div><span>Dernier pointage</span><span>${last ? fmtDate(last.createdAt) : "—"}</span></div>
          </div>
          <div class="folder-foot">${status}<span class="go">Ouvrir ${I.arrow}</span></div>
        </a>`;
      }).join("")}
    </div>
    <p class="muted" style="margin-top:40px;font-size:12px">Dossiers et documents de démonstration — données fictives. <button class="btn btn-ghost btn-sm" id="reset">Réinitialiser la démo</button></p>
  </div>`, [{ label: "Mes dossiers" }]);

  $("#q").addEventListener("input", (e) => {
    const q = e.target.value.trim().toLowerCase();
    $$(".folder").forEach((f) => { f.style.display = f.dataset.name.includes(q) ? "" : "none"; });
  });
  $("#reset").addEventListener("click", () => modal(`
    <h2>Réinitialiser la démo ?</h2>
    <p class="muted" style="margin:0">Tous les pointages, synthèses et envois stockés dans ce navigateur seront supprimés.</p>
    <div class="actions"><button class="btn" data-close>Annuler</button><button class="btn btn-primary" id="ok">Réinitialiser</button></div>`,
    (o, close) => $("#ok", o).addEventListener("click", () => { store.resetAll(); close(); route(); toast("Démo réinitialisée"); })));
}

function statusPill(s) {
  return {
    analysing: '<span class="pill pill-warn"><span class="d"></span>Analyse</span>',
    review: '<span class="pill pill-warn"><span class="d"></span>Pointage en cours</span>',
    finalized: '<span class="pill pill-green"><span class="d"></span>Finalisé</span>',
    sent: '<span class="pill pill-dark"><span class="d" style="background:var(--green)"></span>Envoyé au client</span>',
    failed: '<span class="pill"><span class="d"></span>Interrompu</span>',
  }[s] || "";
}

/* =============================================================================
   Vue 2 — Dossier client : dépôt des deux versions
   ============================================================================= */
function viewFolder(clientId) {
  const c = clientById(clientId);
  if (!c) return notFound();
  const up = (ui.uploads[clientId] ||= { before: null, after: null });
  const history = store.sessionsFor(clientId);

  const dropZone = (side) => {
    const f = up[side];
    const isNew = side === "after";
    return `
    <div class="drop ${f ? "filled" : ""}" data-side="${side}">
      <div class="drop-head">
        <span class="vtag ${isNew ? "new" : ""}"><b>${isNew ? "N" : "N-1"}</b>${isNew ? "Nouvelle version à analyser" : "Version précédente"}</span>
        ${f ? `<button class="btn btn-ghost btn-sm" data-clear="${side}">Retirer</button>` : ""}
      </div>
      <div class="drop-body">
        ${f ? `
          <div class="file-card">
            <div class="pdf-ico"></div>
            <div style="min-width:0">
              <div class="n">${esc(f.name)}</div>
              <div class="muted" style="font-size:12.5px">${fmtSize(f.size)}${f.demo ? " · jeu de démonstration" : ""}</div>
              <div class="hash" title="Empreinte SHA-256 : ${esc(f.sha256)}">${I.shield} SHA-256 ${esc(shortHash(f.sha256))}</div>
            </div>
          </div>` : `
          <div>
            <div class="ico">${I.upload}</div>
            <div style="font-weight:650;color:var(--ink)">Glissez le PDF ici</div>
            <div style="font-size:12.5px;margin:4px 0 12px">ou</div>
            <button class="btn btn-sm" data-pick="${side}">Choisir un fichier</button>
          </div>`}
      </div>
      <input type="file" accept="application/pdf,.pdf" data-input="${side}">
    </div>`;
  };

  mount(`
  <div class="page">
    <a href="#/" class="btn btn-ghost btn-sm" style="margin:-8px 0 14px -10px">${I.back} Mes dossiers</a>
    <div class="client-hero">
      <div class="mono-logo" style="--hue:${c.hue}">${esc(c.short)}</div>
      <div>
        <div class="eyebrow">${esc(c.sector)} · ${esc(c.mission)}</div>
        <h1>${esc(c.name)}</h1>
        <div class="muted">${esc(c.doc)}</div>
      </div>
    </div>

    <div class="upload-grid">
      ${dropZone("before")}
      <div class="vs"><span>VS</span></div>
      ${dropZone("after")}
    </div>
    <div id="err"></div>

    <div class="upload-actions">
      <div class="trust">
        <span>${I.lock} ${api.isRemote() ? "Transfert chiffré TLS 1.3" : "Fichiers traités dans votre navigateur"}</span>
        <span>${I.shield} Empreinte SHA-256 de chaque pièce</span>
        <span>${I.eye} Journal d'audit horodaté</span>
      </div>
      <div style="display:flex;gap:10px;flex-wrap:wrap">
        <button class="btn" id="demo">Utiliser les documents de démonstration</button>
        <button class="btn btn-primary btn-lg" id="go" ${up.before && up.after ? "" : "disabled"}>Lancer l'analyse ${I.arrow}</button>
      </div>
    </div>

    <div class="history">
      <div class="section-title"><h2>Historique des pointages</h2><span class="muted">${plural(history.length, "pointage")}</span></div>
      <div class="card">
        ${history.length ? `
        <table class="table">
          <thead><tr><th>Date</th><th>Versions comparées</th><th>Écarts</th><th>Statut</th><th></th></tr></thead>
          <tbody>${history.map((s) => {
            const st = stats(s.differences || []);
            return `<tr class="clickable" data-open="${s.id}">
              <td>${fmtDateTime(s.createdAt)}</td>
              <td><div>${esc(s.files.before.name)}</div><div class="muted">→ ${esc(s.files.after.name)}</div></td>
              <td class="mono">${s.differences ? `${st.total} · <span style="color:#B42318">${st.confirmed} err.</span>` : "—"}</td>
              <td>${statusPill(s.status)}</td>
              <td style="text-align:right">${I.arrow}</td></tr>`;
          }).join("")}</tbody>
        </table>` : `<div class="empty-state">Aucun pointage pour ce dossier. Déposez deux versions pour commencer.</div>`}
      </div>
    </div>
  </div>`, [{ label: "Mes dossiers", href: "#/" }, { label: c.name }]);

  const showErr = (m) => { $("#err").innerHTML = m ? `<div class="error-box">${esc(m)}</div>` : ""; };
  const accept = async (side, file) => {
    showErr("");
    try { up[side] = await api.inspectFile(file); viewFolder(clientId); }
    catch (e) { showErr(e.message); }
  };

  $$("[data-pick]").forEach((b) => b.addEventListener("click", () => $(`[data-input="${b.dataset.pick}"]`).click()));
  $$("[data-input]").forEach((inp) => inp.addEventListener("change", () => inp.files[0] && accept(inp.dataset.input, inp.files[0])));
  $$("[data-clear]").forEach((b) => b.addEventListener("click", () => { up[b.dataset.clear] = null; viewFolder(clientId); }));
  $$(".drop").forEach((z) => {
    z.addEventListener("dragover", (e) => { e.preventDefault(); z.classList.add("drag"); });
    z.addEventListener("dragleave", () => z.classList.remove("drag"));
    z.addEventListener("drop", (e) => { e.preventDefault(); z.classList.remove("drag"); const f = e.dataTransfer.files[0]; if (f) accept(z.dataset.side, f); });
  });
  $$("[data-open]").forEach((tr) => tr.addEventListener("click", () => openSession(store.getSession(tr.dataset.open))));

  $("#demo").addEventListener("click", async () => {
    showErr("");
    try {
      const load = async (path, name) => {
        const res = await fetch(path);
        if (!res.ok) throw new Error("fetch");
        return api.inspectFile(new File([await res.blob()], name, { type: "application/pdf" }));
      };
      up.before = { ...(await load("samples/URD_2025_v1_precedente.pdf", "URD_2025_v1_precedente.pdf")), demo: true };
      up.after = { ...(await load("samples/URD_2025_v2_nouvelle.pdf", "URD_2025_v2_nouvelle.pdf")), demo: true };
    } catch {
      // Repli : textes embarqués (si les PDF d'exemple ne sont pas servis)
      const mk = async (txt, name) => { const t = txt.replace("{CLIENT}", c.name); const buf = new TextEncoder().encode(t); return { name, size: buf.length, sha256: await api.sha256(buf), text: t, demo: true }; };
      up.before = await mk(DEMO_BEFORE, "URD_2025_v1_precedente.pdf");
      up.after = await mk(DEMO_AFTER, "URD_2025_v2_nouvelle.pdf");
    }
    viewFolder(clientId);
  });

  $("#go").addEventListener("click", () => startAnalysis(clientId));
}

function openSession(s) {
  if (!s) return;
  if (s.status === "review") location.hash = `#/revue/${s.id}`;
  else if (s.status === "finalized" || s.status === "sent") location.hash = `#/synthese/${s.id}`;
  else location.hash = `#/analyse/${s.id}`;
}

/* =============================================================================
   Vue 3 — Analyse (progression puis tableau de bord des écarts)
   ============================================================================= */
async function startAnalysis(clientId) {
  const up = ui.uploads[clientId];
  const meta = (f) => ({ name: f.name, size: f.size, sha256: f.sha256 });
  const s = store.createSession({ clientId, files: { before: meta(up.before), after: meta(up.after) }, mode: api.isRemote() ? "api" : "local" });
  ui.running[s.id] = { steps: {}, error: null };
  location.hash = `#/analyse/${s.id}`;

  try {
    const res = await api.analyze({
      clientId, before: up.before, after: up.after,
      onStep: (key, st) => { ui.running[s.id].steps[key] = st; paintSteps(s.id); },
    });
    s.documents = res.documents;
    s.engine = res.engine;
    s.remoteId = res.id || null;
    s.differences = res.differences.map((d) => ({ ...d, status: "pending", note: "" }));
    s.status = "review";
    s.analysedAt = new Date().toISOString();
    store.log(s, "Analyse terminée", `${plural(s.differences.length, "écart")} détecté${s.differences.length > 1 ? "s" : ""} · moteur ${s.engine}`, "Agent Tickmark");
    ui.uploads[clientId] = { before: null, after: null }; // libère les fichiers bruts de la mémoire
    delete ui.running[s.id];
    if (location.hash === `#/analyse/${s.id}`) viewAnalysis(s.id);
  } catch (e) {
    console.error(e);
    ui.running[s.id].error = e.message || String(e);
    s.status = "failed";
    store.log(s, "Analyse en échec", ui.running[s.id].error);
    if (location.hash === `#/analyse/${s.id}`) viewAnalysis(s.id);
  }
}

function paintSteps(sid) {
  const run = ui.running[sid];
  const box = $("#steps");
  if (!run || !box) return;
  const done = api.ANALYSIS_STEPS.filter((st) => run.steps[st.key] === "done").length;
  box.innerHTML = api.ANALYSIS_STEPS.map((st) => {
    const state = run.steps[st.key] || "pending";
    return `<div class="step ${state}"><span class="st">${state === "done" ? I.check : ""}</span><div><div class="t">${esc(st.label)}</div><div class="h">${esc(st.hint)}</div></div><span class="muted mono" style="font-size:11px">${state === "done" ? "OK" : state === "running" ? "en cours" : ""}</span></div>`;
  }).join("");
  $("#pbar").style.width = `${(done / api.ANALYSIS_STEPS.length) * 100}%`;
}

function viewAnalysis(sid) {
  const s = store.getSession(sid);
  if (!s) return notFound();
  const c = clientById(s.clientId);
  const crumbs = [{ label: "Mes dossiers", href: "#/" }, { label: c.name, href: `#/dossier/${c.id}` }, { label: "Analyse" }];
  const run = ui.running[sid];

  // En cours ou en échec
  if (!s.differences) {
    const err = run?.error || (!run ? "L'analyse a été interrompue (page rechargée)." : null);
    mount(`
    <div class="page analysis">
      <div class="eyebrow">${esc(c.name)} · ${esc(s.files.before.name)} → ${esc(s.files.after.name)}</div>
      <h1 style="font-size:30px;margin:6px 0 4px">${err ? "Analyse interrompue" : "L'agent analyse les deux versions…"}</h1>
      <p class="lead">${err ? esc(err) : "Détection exhaustive : chiffres, mots, ponctuation, espaces et sauts de ligne."}</p>
      <div class="bar" style="margin-top:22px"><i id="pbar" style="width:0"></i></div>
      <div class="card steps" id="steps"></div>
      ${err ? `<a class="btn btn-primary" style="margin-top:18px" href="#/dossier/${c.id}">${I.back} Revenir au dossier</a>` : ""}
    </div>`, crumbs);
    if (run) paintSteps(sid);
    return;
  }

  // Terminé : tableau de bord
  const st = stats(s.differences);
  const cats = CATEGORY_ORDER.filter((k) => st.by[k]);
  mount(`
  <div class="page analysis" style="max-width:1100px">
    <div class="done-hero">
      <div class="done-check">${I.check.replace('width="16" height="16"', 'width="28" height="28"')}</div>
      <div>
        <div class="eyebrow" style="color:#9CA39D">${esc(c.name)} · analyse terminée ${fmtTime(s.analysedAt)}</div>
        <h1>Analyse finie. ${st.total ? "Les écarts sont prêts à être pointés." : "Aucun écart détecté."}</h1>
        <p>${esc(s.files.before.name)} <span style="color:var(--green)">→</span> ${esc(s.files.after.name)} · ${plural(s.documents.after.pageCount || 1, "page")}</p>
      </div>
      <div class="big-num">${st.total}<small>écarts générés</small></div>
    </div>

    ${st.total ? `
    <div class="stack" id="stack" aria-label="Répartition des écarts par catégorie">
      ${cats.filter((k) => st.by[k].total).map((k) => `<div data-cat="${k}" style="flex:${st.by[k].total};background:${catColor(k)}" data-tip="${esc(CATEGORIES[k].label)} : ${st.by[k].total} (${Math.round((st.by[k].total / st.total) * 100)} %)"></div>`).join("")}
    </div>
    <div class="muted" style="font-size:12.5px">Cliquez sur une catégorie pour commencer le pointage à partir de celle-ci.</div>

    <div class="cat-grid">
      ${cats.map((k) => {
        const n = st.by[k].total;
        return `<button class="cat-card" style="--c:${catColor(k)}" data-cat="${k}" ${n ? "" : "disabled"}>
          <div class="lbl"><span class="cat-chip" style="--c:${catColor(k)}">${esc(CATEGORIES[k].short)}</span><span class="sev sev-${n ? severityOf(s, k) : ""}">${n ? SEVERITY[severityOf(s, k)].label : ""}</span></div>
          <div class="n">${n}</div>
          <div style="font-weight:650">${esc(CATEGORIES[k].label)}</div>
          <div class="rule">${esc(CATEGORIES[k].rule)}</div>
          ${n ? `<div class="go">Revoir ${I.arrow}</div>` : ""}
        </button>`;
      }).join("")}
    </div>` : ""}

    <div style="display:flex;justify-content:space-between;align-items:center;margin-top:26px;gap:12px;flex-wrap:wrap">
      <div class="trust"><span>${I.shield} Moteur : <span class="mono">${esc(s.engine)}</span></span><span>${I.fp} Empreintes vérifiées</span></div>
      ${st.total ? `<a class="btn btn-primary btn-lg" href="#/revue/${s.id}">Commencer le pointage ${I.arrow}</a>`
        : `<button class="btn btn-primary btn-lg" id="fin0">Finaliser sans écart</button>`}
    </div>
  </div>`, crumbs);

  const goCat = (k) => { ui.review = { filter: k, activeId: null, sid: s.id }; location.hash = `#/revue/${s.id}`; };
  $$("[data-cat]").forEach((el) => el.addEventListener("click", () => goCat(el.dataset.cat)));
  $("#fin0")?.addEventListener("click", () => finalize(s));
  bindTooltips();
}

function severityOf(s, k) {
  return s.differences.filter((d) => d.category === k).reduce((best, d) => (SEVERITY[d.severity]?.rank ?? 0) > (SEVERITY[best]?.rank ?? -1) ? d.severity : best, "info");
}

function bindTooltips() {
  let tip = null;
  $$("[data-tip]").forEach((el) => {
    el.addEventListener("mousemove", (e) => {
      if (!tip) { tip = document.createElement("div"); tip.className = "tooltip"; document.body.appendChild(tip); }
      tip.textContent = el.dataset.tip;
      tip.style.left = `${e.clientX + 12}px`; tip.style.top = `${e.clientY + 14}px`;
    });
    el.addEventListener("mouseleave", () => { tip?.remove(); tip = null; });
  });
}

/* =============================================================================
   Rendu d'un document avec surlignage des écarts
   ============================================================================= */
/**
 * @param text   texte complet (pages séparées par \f)
 * @param diffs  écarts à surligner
 * @param side   "before" | "after"
 * @param opts   { activeId, numbered: Map(id -> n) }
 */
function renderDoc(text, diffs, side, opts = {}) {
  const spans = diffs.map((d) => {
    const [s, e] = side === "before" ? d.beforeRange : d.afterRange;
    return { s, e, d };
  }).sort((a, b) => a.s - b.s || a.e - b.e);

  let html = "", page = 1, pos = 0;
  const openSheet = () => `<div class="sheet"><span class="sheet-no">p. ${page}</span><pre>`;
  const closeSheet = "</pre></div>";
  html += openSheet();

  const emit = (str, wrapOpen = "", wrapClose = "", visibleWs = false) => {
    const parts = str.split("\f");
    parts.forEach((p, i) => {
      if (i > 0) { html += wrapClose + closeSheet; page++; html += openSheet() + wrapOpen; }
      let t = esc(p);
      if (visibleWs) t = t.replace(/ /g, '<span class="ws">·</span>').replace(/\n/g, '<span class="ws">↵</span>\n');
      html += t;
    });
  };

  for (const { s, e, d } of spans) {
    if (s < pos) continue; // chevauchement improbable : on ignore
    emit(text.slice(pos, s));
    const cls = `${d.status || "pending"}${d.id === opts.activeId ? " active" : ""}`;
    const badge = opts.numbered?.has(d.id) ? `<span class="badge-n" style="--c:${catColor(d.category)}">${opts.numbered.get(d.id)}</span>` : "";
    const title = esc(`${CATEGORIES[d.category]?.label || d.category} · ${d.id}`);
    if (e === s) {
      html += `<span class="caret ${cls}" style="--c:${catColor(d.category)}" data-id="${d.id}" title="${title} — ${side === "before" ? "texte ajouté dans N" : "texte supprimé de N-1"}"></span>${badge}`;
    } else {
      const open = `<span class="hl ${cls}" style="--c:${catColor(d.category)}" data-id="${d.id}" title="${title}">`;
      const isWs = /^\s+$/.test(text.slice(s, e));
      html += open;
      emit(text.slice(s, e), open, "</span>", isWs);
      html += `</span>${badge}`;
    }
    pos = e;
  }
  emit(text.slice(pos));
  html += closeSheet;
  return html;
}

function scrollPaneTo(pane, id) {
  const el = pane?.querySelector(`[data-id="${id}"]`);
  if (!el) return;
  const r = el.getBoundingClientRect(), pr = pane.getBoundingClientRect();
  pane.scrollTo({ top: pane.scrollTop + (r.top - pr.top) - pane.clientHeight / 2 + r.height / 2, behavior: "smooth" });
}

/* =============================================================================
   Vue 4 — Revue / pointage
   ============================================================================= */
let reviewKeyHandler = null;

function viewReview(sid) {
  const s = store.getSession(sid);
  if (!s || !s.differences) return notFound();
  if (s.status !== "review") { location.hash = `#/synthese/${sid}`; return; }
  const c = clientById(s.clientId);
  const R = ui.review;
  if (R.sid !== sid) { R.sid = sid; R.activeId = null; R.filter = "all"; }

  const filtered = () => s.differences.filter((d) => R.filter === "all" || d.category === R.filter);
  if (!R.activeId || !filtered().some((d) => d.id === R.activeId)) {
    const f = filtered();
    R.activeId = (f.find((d) => d.status === "pending") || f[0] || s.differences[0])?.id || null;
  }

  mount(`
  <div class="review">
    <aside class="panel panel-left">
      <div class="panel-head">
        <div class="progress-row"><span class="muted">Progression du pointage</span><b id="prog-txt"></b></div>
        <div class="bar"><i id="prog-bar"></i></div>
      </div>
      <div class="filters" id="filters"></div>
      <div id="bulk"></div>
      <div class="list" id="list" role="listbox" aria-label="Écarts"></div>
      <div class="panel-foot">
        <button class="btn btn-green btn-lg" id="finalize">${I.check} Finaliser le pointage</button>
        <div class="hint" id="fin-hint"></div>
      </div>
    </aside>

    <section class="center">
      <div class="toolbar">
        <div class="finder" aria-label="Navigation entre écarts">
          <button id="prev" title="Écart précédent (↑ ou Maj+Entrée)">${I.up}</button>
          <span class="pos" id="pos"></span>
          <button id="next" title="Écart suivant (↓ ou Entrée)">${I.down}</button>
        </div>
        <span id="filter-label"></span>
        <div class="shortcuts"><span><span class="kbd">↑↓</span> naviguer</span><span><span class="kbd">X</span> pas une erreur</span><span><span class="kbd">N</span> annoter</span><span><span class="kbd">Ctrl ↵</span> valider</span></div>
      </div>
      <div class="docs">
        <div class="doc-pane">
          <div class="doc-head"><span class="vtag"><b>N-1</b></span><span class="fname">${esc(s.files.before.name)}</span><span class="muted">${plural(s.documents.before.pageCount || 1, "page")}</span></div>
          <div class="doc-scroll" id="pane-before"></div>
        </div>
        <div class="doc-pane">
          <div class="doc-head"><span class="vtag new"><b>N</b></span><span class="fname">${esc(s.files.after.name)}</span><span class="muted">${plural(s.documents.after.pageCount || 1, "page")}</span></div>
          <div class="doc-scroll" id="pane-after"></div>
        </div>
      </div>
    </section>

    <aside class="panel panel-right" id="detail-panel"></aside>
  </div>`, [{ label: "Mes dossiers", href: "#/" }, { label: c.name, href: `#/dossier/${c.id}` }, { label: "Pointage" }]);

  const paneB = $("#pane-before"), paneA = $("#pane-after");
  const paintDocs = () => {
    paneB.innerHTML = renderDoc(s.documents.before.text, s.differences, "before", { activeId: R.activeId });
    paneA.innerHTML = renderDoc(s.documents.after.text, s.differences, "after", { activeId: R.activeId });
  };

  const paintProgress = () => {
    const st = stats(s.differences);
    const done = st.total - st.pending;
    $("#prog-txt").textContent = `${done} / ${st.total}`;
    $("#prog-bar").style.width = `${st.total ? (done / st.total) * 100 : 100}%`;
    $("#finalize").disabled = st.pending > 0;
    $("#fin-hint").innerHTML = st.pending ? `${plural(st.pending, "écart restant", "écarts restants")} à traiter` : `${st.confirmed} erreur(s) · ${st.dismissed} écartée(s) — prêt`;

    $("#filters").innerHTML = [["all", "Tous les écarts", "var(--ink)", st]]
      .concat(CATEGORY_ORDER.filter((k) => st.by[k]?.total).map((k) => [k, CATEGORIES[k].label, catColor(k), st.by[k]]))
      .map(([k, label, color, b]) => `<button class="filter ${R.filter === k ? "on" : ""}" data-filter="${k}" style="--c:${color}">
        <span class="sw"></span><span>${esc(label)}</span><span class="cnt"><b>${b.total - b.pending}</b>/${b.total}</span></button>`).join("");
    $$("[data-filter]").forEach((b) => b.addEventListener("click", () => setFilter(b.dataset.filter)));

    const cur = R.filter !== "all" ? st.by[R.filter] : null;
    $("#bulk").innerHTML = cur && cur.pending > 0 && ["mise_en_forme", "ponctuation"].includes(R.filter)
      ? `<div style="padding:8px 12px;border-bottom:1px solid var(--line)"><button class="btn btn-sm" style="width:100%" id="bulk-btn">${I.x} Écarter les ${cur.pending} écarts « ${esc(CATEGORIES[R.filter].short)} » restants</button></div>` : "";
    $("#bulk-btn")?.addEventListener("click", bulkDismiss);
  };

  const paintList = () => {
    const list = filtered();
    $("#list").innerHTML = list.map((d) => {
      const n = s.differences.indexOf(d) + 1;
      const icon = d.status === "confirmed" ? `<span style="color:var(--green-ink)">${I.check}</span>` : d.status === "dismissed" ? `<span class="muted">${I.x.replace(/18/g, "14")}</span>` : '<span class="st-dot"></span>';
      return `<button class="item ${d.id === R.activeId ? "active" : ""} ${d.status}" style="--c:${catColor(d.category)}" data-id="${d.id}" role="option" aria-selected="${d.id === R.activeId}">
        <span class="num">${String(n).padStart(2, "0")}</span>
        <span class="what">
          <span class="ba">${d.before ? `<del>${esc(compact(d.before))}</del>` : ""}${d.before && d.after ? " → " : ""}${d.after ? `<ins>${esc(compact(d.after))}</ins>` : ""}</span>
          <span class="loc"><span style="color:${catColor(d.category)}">●</span> ${esc(CATEGORIES[d.category]?.short || d.category)} · p.${d.page} · ${esc(d.section || "")}</span>
        </span>
        <span class="stt">${icon}</span>
      </button>`;
    }).join("") || '<div class="empty-state">Aucun écart dans ce filtre.</div>';
    $$("#list .item").forEach((b) => b.addEventListener("click", () => select(b.dataset.id)));
    $("#list .item.active")?.scrollIntoView({ block: "nearest" });

    const idx = list.findIndex((d) => d.id === R.activeId);
    $("#pos").innerHTML = `${idx + 1} <span class="muted">/ ${list.length}</span>`;
    $("#filter-label").innerHTML = R.filter === "all" ? '<span class="muted" style="font-size:12.5px">Toutes catégories</span>' : `<span class="cat-chip" style="--c:${catColor(R.filter)}">${esc(CATEGORIES[R.filter].label)}</span>`;
  };

  const paintDetail = () => {
    const d = s.differences.find((x) => x.id === R.activeId);
    const panel = $("#detail-panel");
    if (!d) { panel.innerHTML = '<div class="empty-state">Sélectionnez un écart.</div>'; return; }
    const n = s.differences.indexOf(d) + 1;
    const conf = Math.round((d.confidence ?? 0.9) * 100);
    panel.innerHTML = `
      <div class="detail">
        <div class="detail-top">
          <span class="cat-chip" style="--c:${catColor(d.category)}">${esc(CATEGORIES[d.category]?.label || d.category)}</span>
          <span class="sev sev-${d.severity}">${esc(SEVERITY[d.severity]?.label || "")}</span>
          <span class="id">#${String(n).padStart(2, "0")} · ${esc(d.id)}</span>
        </div>
        <div class="loc-line">Page ${d.page} · ${esc(d.section || "")}</div>
        <div class="cmp">
          <div class="cmp-box b"><div class="k"><span>Version précédente · N-1</span></div><div class="v">${d.before ? showVal(d, d.before) : '<span class="empty">— absent —</span>'}</div></div>
          <div class="cmp-box a"><div class="k"><span>Nouvelle version · N</span></div><div class="v">${d.after ? showVal(d, d.after) : '<span class="empty">— absent —</span>'}</div></div>
        </div>
        <div class="agent">
          <div class="agent-h"><span class="ai">IA</span>Analyse de l'agent · ${esc(d.subtype || "")}</div>
          <p>${esc(d.rationale || "")}</p>
          <div class="conf"><span>Confiance</span><div class="bar"><i style="width:${conf}%"></i></div><span class="mono">${conf} %</span></div>
        </div>
        ${d.context ? `<div class="ctx"><span class="muted">Contexte (N) :</span> ${esc(d.context)}</div>` : ""}
      </div>
      <div class="decision">
        ${d.status !== "pending" ? `
          <div class="status-banner ${d.status}">
            <span>${d.status === "confirmed" ? `${I.check} Erreur confirmée` : `${I.x.replace(/18/g, "14")} Pas une erreur`} · ${esc(d.reviewedBy || "")} ${fmtTime(d.reviewedAt)}</span>
            <button class="btn btn-sm btn-ghost" id="reopen">Rouvrir</button>
          </div>` : ""}
        <h4>Note d'audit</h4>
        <textarea id="note" placeholder="Ex. : Erreur relative à la note 12 — le montant doit être corrigé à 7 412 M€ conformément aux comptes consolidés.">${esc(d.note || "")}</textarea>
        <div class="quick">
          ${["À corriger par le client", "Rapprocher de la balance", "Incohérence avec une autre section", "Demander un justificatif"].map((q) => `<button data-q="${esc(q)}">${esc(q)}</button>`).join("")}
        </div>
        <div class="decision-row">
          <button class="btn btn-danger-soft x-btn" id="dismiss" title="Ce n'est pas une erreur (X)">${I.x}</button>
          <button class="btn btn-primary" id="confirm" style="height:44px">${I.pen} Valider l'écart <span class="kbd" style="border-color:#fff">Ctrl ↵</span></button>
        </div>
      </div>`;

    $$("[data-q]", panel).forEach((b) => b.addEventListener("click", () => {
      const ta = $("#note"); ta.value = (ta.value.trim() ? ta.value.trim() + " — " : "") + b.dataset.q; ta.focus();
    }));
    $("#dismiss").addEventListener("click", () => decide("dismissed"));
    $("#confirm").addEventListener("click", () => decide("confirmed"));
    $("#reopen")?.addEventListener("click", () => {
      store.log(s, "Écart rouvert", d.id);
      Object.assign(d, { status: "pending", reviewedAt: null, reviewedBy: null });
      refresh(false);
    });
  };

  const refresh = (docs = true) => { paintProgress(); paintList(); paintDetail(); if (docs) paintDocs(); else updateHl(); };
  const updateHl = () => {
    for (const pane of [paneB, paneA]) {
      $$("[data-id]", pane).forEach((el) => {
        const d = s.differences.find((x) => x.id === el.dataset.id);
        el.classList.remove("pending", "confirmed", "dismissed", "active");
        el.classList.add(d.status || "pending");
        if (d.id === R.activeId) el.classList.add("active");
      });
    }
  };

  function select(id, scroll = true) {
    R.activeId = id;
    paintList(); paintDetail(); updateHl();
    if (scroll) { scrollPaneTo(paneB, id); scrollPaneTo(paneA, id); }
  }
  function setFilter(k) {
    R.filter = k;
    const f = filtered();
    const keep = f.find((d) => d.id === R.activeId);
    R.activeId = keep ? keep.id : (f.find((d) => d.status === "pending") || f[0])?.id;
    paintProgress(); select(R.activeId);
  }
  function step(dir) {
    const f = filtered();
    if (!f.length) return;
    const i = f.findIndex((d) => d.id === R.activeId);
    select(f[(i + dir + f.length) % f.length].id); // boucle comme un Ctrl+F
  }
  function decide(status) {
    const d = s.differences.find((x) => x.id === R.activeId);
    if (!d) return;
    d.status = status;
    d.note = status === "confirmed" ? $("#note").value.trim() : ($("#note").value.trim() || "");
    d.reviewedBy = store.userName();
    d.reviewedAt = new Date().toISOString();
    store.log(s, status === "confirmed" ? "Erreur confirmée" : "Écart écarté (pas une erreur)", `${d.id} · ${CATEGORIES[d.category]?.short}${d.note ? " · « " + d.note.slice(0, 80) + " »" : ""}`);
    api.saveReview(s).catch((e) => toast(e.message));
    // Écart suivant non traité (dans le filtre, puis global)
    const f = filtered();
    const i = f.findIndex((x) => x.id === d.id);
    const next = [...f.slice(i + 1), ...f.slice(0, i)].find((x) => x.status === "pending")
      || s.differences.find((x) => x.status === "pending");
    if (next && !f.includes(next)) R.filter = "all";
    paintProgress();
    if (next) select(next.id);
    else { select(d.id, false); toast("Tous les écarts sont traités — vous pouvez finaliser le pointage."); }
  }
  function bulkDismiss() {
    const pend = filtered().filter((d) => d.status === "pending");
    modal(`
      <h2>Écarter ${plural(pend.length, "écart")} ?</h2>
      <p class="muted" style="margin:0">Catégorie « ${esc(CATEGORIES[R.filter].label)} » : ${esc(CATEGORIES[R.filter].rule)} Chaque écart sera tracé individuellement dans le journal d'audit.</p>
      <div class="actions"><button class="btn" data-close>Annuler</button><button class="btn btn-primary" id="ok">Écarter</button></div>`,
      (o, close) => $("#ok", o).addEventListener("click", () => {
        const now = new Date().toISOString();
        pend.forEach((d) => Object.assign(d, { status: "dismissed", reviewedBy: store.userName(), reviewedAt: now }));
        store.log(s, "Écarts écartés en masse", `${pend.length} × ${CATEGORIES[R.filter].short} (${pend.map((d) => d.id).join(", ")})`);
        api.saveReview(s).catch((e) => toast(e.message));
        close(); R.filter = "all";
        const next = s.differences.find((x) => x.status === "pending");
        paintProgress(); select((next || s.differences[0]).id);
      }));
  }

  $("#prev").addEventListener("click", () => step(-1));
  $("#next").addEventListener("click", () => step(1));
  $("#finalize").addEventListener("click", () => finalize(s));
  for (const pane of [paneB, paneA]) {
    pane.addEventListener("click", (e) => { const el = e.target.closest("[data-id]"); if (el) select(el.dataset.id); });
  }

  if (reviewKeyHandler) document.removeEventListener("keydown", reviewKeyHandler);
  reviewKeyHandler = (e) => {
    if (!location.hash.startsWith("#/revue/") || $(".overlay")) return;
    const typing = e.target.matches("textarea, input");
    if (typing) {
      if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); decide("confirmed"); }
      if (e.key === "Escape") e.target.blur();
      return;
    }
    if (e.key === "ArrowDown" || e.key === "j" || (e.key === "Enter" && !e.shiftKey && !e.target.matches("button"))) { e.preventDefault(); step(1); }
    else if (e.key === "ArrowUp" || e.key === "k" || (e.key === "Enter" && e.shiftKey)) { e.preventDefault(); step(-1); }
    else if (e.key === "x" || e.key === "X") { e.preventDefault(); decide("dismissed"); }
    else if (e.key === "n" || e.key === "N") { e.preventDefault(); $("#note")?.focus(); }
    else if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); decide("confirmed"); }
  };
  document.addEventListener("keydown", reviewKeyHandler);

  refresh(true);
  requestAnimationFrame(() => { scrollPaneTo(paneB, R.activeId); scrollPaneTo(paneA, R.activeId); });
}

function finalize(s) {
  const st = stats(s.differences);
  if (st.pending) return;
  modal(`
    <h2>Finaliser le pointage</h2>
    <p class="muted" style="margin:0">La revue sera verrouillée et la synthèse générée.</p>
    <div class="recap">
      <div><span>Écarts détectés par l'agent</span><b>${st.total}</b></div>
      <div><span>Erreurs confirmées (avec notes)</span><b style="color:#B42318">${st.confirmed}</b></div>
      <div><span>Écartés (pas une erreur)</span><b>${st.dismissed}</b></div>
    </div>
    <label class="check"><input type="checkbox" id="att"> J'atteste avoir revu l'ensemble des écarts détectés. Ma validation est horodatée et tracée.</label>
    <div class="actions"><button class="btn" data-close>Annuler</button><button class="btn btn-green" id="ok" disabled>${I.check} Finaliser</button></div>`,
    (o, close) => {
      $("#att", o).addEventListener("change", (e) => { $("#ok", o).disabled = !e.target.checked; });
      $("#ok", o).addEventListener("click", () => {
        s.status = "finalized";
        s.finalizedAt = new Date().toISOString();
        store.log(s, "Pointage finalisé", `${st.confirmed} erreur(s) confirmée(s), ${st.dismissed} écartée(s) — attestation de revue`);
        api.saveReview(s).catch((e) => toast(e.message));
        close();
        location.hash = `#/synthese/${s.id}`;
      });
    });
}

/* =============================================================================
   Vue 5 — Synthèse (et rapport côté client)
   ============================================================================= */
function errorsList(errs, numbered) {
  if (!errs.length) return '<div class="empty-state">Aucune erreur confirmée : les deux versions sont concordantes après revue.</div>';
  return `<div class="err-list">${errs.map((d) => `
    <div class="err" style="--c:${catColor(d.category)}">
      <span class="no">${numbered.get(d.id)}</span>
      <div>
        <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap"><span class="cat-chip" style="--c:${catColor(d.category)}">${esc(CATEGORIES[d.category]?.short || d.category)}</span><span class="muted" style="font-size:12px">Page ${d.page} · ${esc(d.section || "")}</span></div>
        <div class="ba">${d.before ? `<del>${showVal(d, d.before)}</del>` : '<span class="muted">(absent)</span>'} → ${d.after ? `<ins>${showVal(d, d.after)}</ins>` : '<span class="muted">(supprimé)</span>'}</div>
        <div class="note ${d.note ? "" : "empty"}">${d.note ? esc(d.note) : "Pas de note"}</div>
      </div>
    </div>`).join("")}</div>`;
}

function docsPair(files, documents, errs, numbered) {
  return `<div class="docs">
    <div class="doc-pane"><div class="doc-head"><span class="vtag"><b>N-1</b></span><span class="fname">${esc(files.before.name)}</span></div><div class="doc-scroll">${renderDoc(documents.before.text, errs, "before", { numbered })}</div></div>
    <div class="doc-pane"><div class="doc-head"><span class="vtag new"><b>N</b></span><span class="fname">${esc(files.after.name)}</span></div><div class="doc-scroll">${renderDoc(documents.after.text, errs, "after", { numbered })}</div></div>
  </div>`;
}

function viewSynthesis(sid) {
  const s = store.getSession(sid);
  if (!s || !s.differences) return notFound();
  if (s.status === "review") { location.hash = `#/revue/${sid}`; return; }
  const c = clientById(s.clientId);
  const st = stats(s.differences);
  const errs = s.differences.filter((d) => d.status === "confirmed");
  const numbered = new Map(errs.map((d, i) => [d.id, i + 1]));
  const mins = Math.max(1, Math.round((new Date(s.finalizedAt) - new Date(s.analysedAt)) / 60000));
  const report = store.reportsFor(s.clientId).find((r) => r.sessionId === s.id);

  mount(`
  <div class="page" style="max-width:1320px">
    ${s.status === "sent" ? `<div class="sent-banner">${I.send} Synthèse transmise à ${esc(c.name)} le ${fmtDateTime(s.sentAt)} via le portail client sécurisé.
      <a class="btn btn-sm no-print" style="margin-left:auto" href="#/client/${report?.id || ""}" id="see-client">Voir côté client ${I.arrow}</a></div>` : ""}
    <div class="synth-head">
      <div>
        <div class="eyebrow">${esc(c.name)} · ${esc(c.mission)}</div>
        <h1>Synthèse du pointage</h1>
        <div class="muted">${esc(s.files.before.name)} → ${esc(s.files.after.name)} · finalisé le ${fmtDateTime(s.finalizedAt)} par ${esc(s.createdBy)}</div>
      </div>
      <div style="display:flex;gap:10px;flex-wrap:wrap" class="no-print">
        <button class="btn" id="print">${I.print} Exporter PDF</button>
        <button class="btn" id="json">${I.dl} Exporter JSON</button>
        ${s.status === "sent" ? "" : `<button class="btn btn-primary btn-lg" id="send">${I.send} Envoyer au client</button>`}
      </div>
    </div>

    <div class="synth-kpis">
      <div class="card kpi"><div class="v">${st.total}</div><div class="l">Écarts détectés par l'agent</div></div>
      <div class="card kpi"><div class="v red">${st.confirmed}</div><div class="l">Erreurs confirmées à corriger</div></div>
      <div class="card kpi"><div class="v">${st.dismissed}</div><div class="l">Écartés (pas une erreur)</div></div>
      <div class="card kpi"><div class="v green">${mins} min</div><div class="l">Durée de revue</div></div>
    </div>

    <div class="two-col">
      <div class="card box">
        <h3>Erreurs à corriger <span class="pill">${errs.length}</span></h3>
        ${errorsList(errs, numbered)}
      </div>
      <div style="display:grid;gap:16px">
        <div class="card box">
          <h3>Par catégorie</h3>
          <table class="table cat-table">
            <thead><tr><th>Catégorie</th><th>Détectés</th><th>Erreurs</th><th>Écartés</th></tr></thead>
            <tbody>${CATEGORY_ORDER.filter((k) => st.by[k]?.total).map((k) => `<tr><td><span class="cat-chip" style="--c:${catColor(k)}">${esc(CATEGORIES[k].short)}</span></td><td>${st.by[k].total}</td><td><b>${st.by[k].confirmed}</b></td><td>${st.by[k].dismissed}</td></tr>`).join("")}</tbody>
          </table>
        </div>
        <div class="card box">
          <h3>Sécurité & intégrité ${I.shield}</h3>
          <div class="integrity">
            <div class="row"><b>Empreinte SHA-256 · N-1</b><span class="mono" style="font-size:11px;word-break:break-all">${esc(s.files.before.sha256)}</span></div>
            <div class="row"><b>Empreinte SHA-256 · N</b><span class="mono" style="font-size:11px;word-break:break-all">${esc(s.files.after.sha256)}</span></div>
            <div class="row"><b>Moteur d'analyse</b><span class="muted">${esc(s.engine)} · ${s.mode === "api" ? "API sécurisée" : "exécution locale (aucune donnée transmise)"}</span></div>
            <div class="row"><b>Partage client</b><span class="muted">Uniquement les erreurs confirmées et leurs notes. Les écarts écartés et le journal restent internes.</span></div>
          </div>
          <details class="audit" style="margin-top:14px">
            <summary>Journal d'audit (${s.audit.length} événements)</summary>
            <table class="table audit-table"><tbody>${s.audit.map((a) => `<tr><td class="mono" style="white-space:nowrap">${fmtDateTime(a.at)}</td><td><b>${esc(a.action)}</b><div class="muted">${esc(a.detail)}</div></td><td class="muted" style="white-space:nowrap">${esc(a.by)}</td></tr>`).join("")}</tbody></table>
          </details>
        </div>
      </div>
    </div>

    <div class="card box synth-docs">
      <h3>Documents annotés <span class="muted" style="font-weight:500;font-size:12.5px">Seules les erreurs confirmées sont surlignées · numéros = liste ci-dessus</span></h3>
      ${docsPair(s.files, s.documents, errs, numbered)}
    </div>
  </div>`, [{ label: "Mes dossiers", href: "#/" }, { label: c.name, href: `#/dossier/${c.id}` }, { label: "Synthèse" }]);

  $("#print").addEventListener("click", () => window.print());
  $("#json").addEventListener("click", () => {
    const payload = buildReport(s);
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    const a = Object.assign(document.createElement("a"), { href: URL.createObjectURL(blob), download: `tickmark_${c.id}_${s.id}.json` });
    a.click(); URL.revokeObjectURL(a.href);
    store.log(s, "Export JSON", a.download);
  });
  $("#see-client")?.addEventListener("click", () => { ui.role = "client"; ui.clientEntity = s.clientId; try { sessionStorage.setItem("tickmark.role", "client"); } catch { /* */ } });
  $("#send")?.addEventListener("click", () => sendModal(s));
}

function buildReport(s) {
  const errs = s.differences.filter((d) => d.status === "confirmed");
  return {
    id: store.uid("rp"),
    sessionId: s.id,
    clientId: s.clientId,
    sentAt: new Date().toISOString(),
    sentBy: store.userName(),
    files: s.files,
    documents: s.documents,
    stats: { detected: s.differences.length, errors: errs.length },
    errors: errs.map(({ id, category, severity, before, after, beforeRange, afterRange, page, section, note }) => ({ id, category, severity, before, after, beforeRange, afterRange, page, section, note, status: "confirmed" })),
  };
}

function sendModal(s) {
  const c = clientById(s.clientId);
  const st = stats(s.differences);
  modal(`
    <h2>Envoyer la synthèse à ${esc(c.name)}</h2>
    <div class="recap">
      <div><span>Destinataire</span><b>${esc(c.name)} · Direction financière</b></div>
      <div><span>Canal</span><b>Portail client sécurisé</b></div>
      <div><span>Contenu partagé</span><b>${plural(st.confirmed, "erreur")} + notes + 2 documents</b></div>
      <div><span>Non partagé</span><b>${st.dismissed} écarts écartés, journal interne</b></div>
    </div>
    <label class="check"><input type="checkbox" id="att"> Je confirme le destinataire et le périmètre du partage (principe du besoin d'en connaître).</label>
    <div class="actions"><button class="btn" data-close>Annuler</button><button class="btn btn-primary" id="ok" disabled>${I.send} Envoyer</button></div>`,
    (o, close) => {
      $("#att", o).addEventListener("change", (e) => { $("#ok", o).disabled = !e.target.checked; });
      $("#ok", o).addEventListener("click", async () => {
        $("#ok", o).disabled = true;
        try {
          const report = buildReport(s);
          await api.sendToClient(s, report);
          store.addReport(report);
          s.status = "sent"; s.sentAt = report.sentAt;
          store.log(s, "Synthèse envoyée au client", `${c.name} · rapport ${report.id} · ${report.errors.length} erreur(s)`);
          close(); viewSynthesis(s.id); toast(`Synthèse envoyée à ${c.name}`);
        } catch (e) { toast(e.message); $("#ok", o).disabled = false; }
      });
    });
}

/* =============================================================================
   Vue 6 — Portail client
   ============================================================================= */
function viewClientHome() {
  ui.role = "client";
  const entity = clientById(ui.clientEntity) || CLIENTS[0];
  const reports = store.reportsFor(entity.id);
  mount(`
  <div class="page">
    <div class="client-banner">
      <div>
        <div class="eyebrow" style="color:#9CA39D">Espace client sécurisé</div>
        <h1>${esc(entity.name)} — Direction financière</h1>
        <p>Retrouvez les synthèses de pointage transmises par votre équipe d'audit Deloitte.</p>
      </div>
      <label><span class="sr-only">Entité</span>
        <select id="entity">${CLIENTS.map((c) => `<option value="${c.id}" ${c.id === entity.id ? "selected" : ""}>${esc(c.name)}</option>`).join("")}</select>
      </label>
    </div>
    <div class="card">
      ${reports.length ? `<table class="table">
        <thead><tr><th>Reçu le</th><th>Document</th><th>Erreurs à corriger</th><th>Émis par</th><th>Statut</th><th></th></tr></thead>
        <tbody>${reports.map((r) => `<tr class="clickable" data-r="${r.id}">
          <td>${fmtDateTime(r.sentAt)}</td><td>${esc(r.files.after.name)}</td><td><b>${r.errors.length}</b></td><td>${esc(r.sentBy)}</td>
          <td>${r.ackAt ? '<span class="pill pill-green"><span class="d"></span>Accusé de réception</span>' : '<span class="pill pill-warn"><span class="d"></span>Nouveau</span>'}</td><td>${I.arrow}</td></tr>`).join("")}</tbody>
      </table>` : `<div class="empty-state">Aucune synthèse reçue pour ${esc(entity.name)}.<br><span style="font-size:12.5px">Côté auditeur : finalisez un pointage puis « Envoyer au client ».</span></div>`}
    </div>
  </div>`, [{ label: "Espace client" }]);
  $("#entity").addEventListener("change", (e) => { ui.clientEntity = e.target.value; viewClientHome(); });
  $$("[data-r]").forEach((tr) => tr.addEventListener("click", () => { location.hash = `#/client/${tr.dataset.r}`; }));
}

function viewClientReport(rid) {
  const r = store.getReport(rid);
  if (!r) return viewClientHome();
  ui.role = "client";
  const c = clientById(r.clientId);
  ui.clientEntity = c.id;
  const numbered = new Map(r.errors.map((d, i) => [d.id, i + 1]));
  mount(`
  <div class="page" style="max-width:1320px">
    <a href="#/client" class="btn btn-ghost btn-sm" style="margin:-8px 0 14px -10px">${I.back} Mes synthèses</a>
    <div class="synth-head">
      <div>
        <div class="eyebrow">${esc(c.name)} · transmis par ${esc(r.sentBy)} (Deloitte) le ${fmtDateTime(r.sentAt)}</div>
        <h1>Synthèse de pointage — ${esc(r.files.after.name)}</h1>
        <div class="muted">${plural(r.errors.length, "erreur")} à corriger avant publication.</div>
      </div>
      <div style="display:flex;gap:10px" class="no-print">
        <button class="btn" id="print">${I.print} Exporter PDF</button>
        ${r.ackAt ? `<span class="pill pill-green" style="height:40px;padding:0 14px">${I.check} Reçu le ${fmtDateTime(r.ackAt)}</span>` : `<button class="btn btn-green btn-lg" id="ack">${I.check} Accuser réception</button>`}
      </div>
    </div>
    <div class="two-col">
      <div class="card box"><h3>Erreurs à corriger <span class="pill">${r.errors.length}</span></h3>${errorsList(r.errors, numbered)}</div>
      <div class="card box">
        <h3>Intégrité ${I.shield}</h3>
        <div class="integrity">
          <div class="row"><b>Version précédente</b><span class="muted">${esc(r.files.before.name)}</span><span class="mono" style="font-size:11px;word-break:break-all">${esc(r.files.before.sha256)}</span></div>
          <div class="row"><b>Nouvelle version</b><span class="muted">${esc(r.files.after.name)}</span><span class="mono" style="font-size:11px;word-break:break-all">${esc(r.files.after.sha256)}</span></div>
          <p class="muted" style="font-size:12.5px;margin:4px 0 0">Comparez ces empreintes avec vos fichiers pour vérifier que la revue porte bien sur vos documents.</p>
        </div>
      </div>
    </div>
    <div class="card box synth-docs"><h3>Documents annotés</h3>${docsPair(r.files, r.documents, r.errors, numbered)}</div>
  </div>`, [{ label: "Espace client", href: "#/client" }, { label: "Synthèse" }]);
  $("#print").addEventListener("click", () => window.print());
  $("#ack")?.addEventListener("click", () => {
    r.ackAt = new Date().toISOString();
    const s = store.getSession(r.sessionId);
    if (s) store.log(s, "Accusé de réception client", r.id, `${c.name} (client)`); else store.persist();
    viewClientReport(rid); toast("Accusé de réception envoyé à l'équipe d'audit");
  });
}

/* =============================================================================
   Sécurité : verrouillage après inactivité
   ============================================================================= */
let lastActivity = Date.now();
["mousemove", "keydown", "click", "scroll"].forEach((ev) => window.addEventListener(ev, () => { lastActivity = Date.now(); }, { passive: true }));
if (CONFIG.IDLE_LOCK_MINUTES > 0) {
  setInterval(() => {
    if (Date.now() - lastActivity > CONFIG.IDLE_LOCK_MINUTES * 60000 && !$(".overlay.locked")) {
      const close = modal(`<div class="lock"><div class="ico">${I.lock.replace(/14/g, "26")}</div></div>
        <h2 style="text-align:center">Session verrouillée</h2>
        <p class="muted" style="margin:0;text-align:center">Inactivité de plus de ${CONFIG.IDLE_LOCK_MINUTES} minutes. Les documents restent masqués jusqu'à la réauthentification.</p>
        <div class="actions" style="justify-content:center"><button class="btn btn-primary" id="unlock">Se réauthentifier (SSO)</button></div>`,
        (o) => { o.classList.add("locked"); o.style.backdropFilter = "blur(14px)"; o.addEventListener("click", (e) => e.stopPropagation(), true); $("#unlock", o).addEventListener("click", () => { lastActivity = Date.now(); o.remove(); }); });
      void close;
    }
  }, 20000);
}

/* =============================================================================
   Routeur
   ============================================================================= */
function notFound() {
  mount(`<div class="page"><h1>Introuvable</h1><p class="muted">Ce pointage n'existe pas (ou a été supprimé de ce navigateur).</p><a class="btn btn-primary" href="#/">Retour aux dossiers</a></div>`, []);
}

function route() {
  const [path] = location.hash.replace(/^#/, "").split("?");
  const parts = path.split("/").filter(Boolean);
  window.scrollTo(0, 0);
  if (parts[0] === "client") { if (parts[1]) viewClientReport(parts[1]); else viewClientHome(); return; }
  if (ui.role === "client") { ui.role = "auditor"; try { sessionStorage.setItem("tickmark.role", "auditor"); } catch { /* */ } }
  switch (parts[0]) {
    case undefined: return viewHome();
    case "dossier": return viewFolder(parts[1]);
    case "analyse": return viewAnalysis(parts[1]);
    case "revue": return viewReview(parts[1]);
    case "synthese": return viewSynthesis(parts[1]);
    default: return notFound();
  }
}

window.addEventListener("hashchange", route);
route();
