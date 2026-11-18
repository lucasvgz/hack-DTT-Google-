/**
 * Couche d'accès back-end — POINT DE MERGE avec l'équipe back.
 * -----------------------------------------------------------------------------
 * Chaque fonction a deux implémentations :
 *   - REMOTE : appelle l'API (CONFIG.API_BASE_URL renseigné) — contrat dans docs/API_CONTRACT.md
 *   - LOCAL  : moteur embarqué (js/diff-engine.js) pour la démo, aucune donnée ne quitte le navigateur
 * L'UI n'appelle QUE ces fonctions : le back-end peut évoluer sans toucher aux vues.
 */
import { CONFIG } from "./config.js";
import { diffDocuments } from "./diff-engine.js";
import { extractPdfText } from "./pdf-extract.js";

export const isRemote = () => Boolean(CONFIG.API_BASE_URL);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function http(path, opts = {}) {
  const res = await fetch(CONFIG.API_BASE_URL.replace(/\/$/, "") + path, {
    credentials: "include", // cookie de session HttpOnly géré par le back-end (SSO)
    ...opts,
    headers: { Accept: "application/json", ...(opts.headers || {}) },
  });
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`;
    try { const j = await res.json(); msg = j.error?.message || j.message || msg; } catch { /* corps non JSON */ }
    throw new Error(`API : ${msg}`);
  }
  return res.status === 204 ? null : res.json();
}

/** Empreinte SHA-256 (preuve d'intégrité des pièces auditées). */
export async function sha256(buffer) {
  const h = await crypto.subtle.digest("SHA-256", buffer);
  return [...new Uint8Array(h)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

/** Lit un File PDF : vérifie la signature, calcule l'empreinte. */
export async function inspectFile(file) {
  if (file.size > CONFIG.MAX_FILE_MB * 1024 * 1024) throw new Error(`Fichier trop volumineux (max ${CONFIG.MAX_FILE_MB} Mo).`);
  const buf = await file.arrayBuffer();
  const head = new TextDecoder().decode(new Uint8Array(buf.slice(0, 5)));
  if (head !== "%PDF-") throw new Error(`« ${file.name} » n'est pas un PDF valide (signature de fichier incorrecte).`);
  return { name: file.name, size: file.size, sha256: await sha256(buf), buffer: buf };
}

export const ANALYSIS_STEPS = [
  { key: "integrity", label: "Contrôle d'intégrité", hint: "Signature PDF + empreinte SHA-256" },
  { key: "extract", label: "Extraction du texte", hint: "Lecture page par page des deux versions" },
  { key: "align", label: "Alignement des versions", hint: "Mise en correspondance ligne à ligne" },
  { key: "detect", label: "Détection exhaustive des écarts", hint: "Comparaison mot à mot, espaces inclus" },
  { key: "classify", label: "Catégorisation par l'agent", hint: "Critères objectifs + justification" },
];

/**
 * Lance la comparaison.
 * @returns {Promise<{documents:{before:{text,pageCount},after:{text,pageCount}}, differences:Array, engine:string}>}
 */
export async function analyze({ clientId, before, after, onStep }) {
  const step = async (key, fn) => {
    onStep?.(key, "running");
    const t0 = performance.now();
    const out = await fn();
    const wait = CONFIG.DEMO_STEP_MS - (performance.now() - t0);
    if (!isRemote() && wait > 0) await sleep(wait);
    onStep?.(key, "done");
    return out;
  };

  if (isRemote()) {
    await step("integrity", async () => {});
    const form = new FormData();
    form.append("clientId", clientId);
    form.append("before", new Blob([before.buffer], { type: "application/pdf" }), before.name);
    form.append("after", new Blob([after.buffer], { type: "application/pdf" }), after.name);
    form.append("beforeSha256", before.sha256);
    form.append("afterSha256", after.sha256);
    onStep?.("extract", "running");
    const result = await http("/api/v1/comparisons", { method: "POST", body: form });
    for (const k of ["extract", "align", "detect", "classify"]) onStep?.(k, "done");
    return { ...result, engine: result.engine || "api" };
  }

  await step("integrity", async () => {});
  const docs = await step("extract", async () => {
    const [a, b] = await Promise.all([readDoc(before), readDoc(after)]);
    return { before: a, after: b };
  });
  await step("align", async () => {});
  const differences = await step("detect", async () => diffDocuments(docs.before.text, docs.after.text));
  await step("classify", async () => {});
  return { documents: docs, differences, engine: "local-rules-v1" };
}

async function readDoc(f) {
  if (typeof f.text === "string") return { text: f.text, pageCount: f.text.split("\f").length };
  return extractPdfText(f.buffer.slice(0));
}

/** Enregistre la revue (statuts + notes). */
export async function saveReview(session) {
  if (!isRemote()) return;
  await http(`/api/v1/comparisons/${encodeURIComponent(session.remoteId || session.id)}/review`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      differences: session.differences.map(({ id, status, note, reviewedBy, reviewedAt }) => ({ id, status, note, reviewedBy, reviewedAt })),
    }),
  });
}

/** Envoie la synthèse au portail client (seules les erreurs confirmées). */
export async function sendToClient(session, report) {
  if (!isRemote()) return report;
  return http(`/api/v1/comparisons/${encodeURIComponent(session.remoteId || session.id)}/send`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(report),
  });
}
