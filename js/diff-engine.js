/**
 * Moteur de diff LOCAL (fallback / démo).
 * -----------------------------------------------------------------------------
 * Rôle : produire exactement le même format que l'API back-end (voir docs/API_CONTRACT.md)
 * pour que l'UI fonctionne sans serveur. Le back-end (agent IA) remplace ce module
 * en renvoyant le même JSON — l'UI ne fait aucune différence.
 *
 * Pipeline :
 *   1. Diff ligne à ligne (Myers) pour isoler les blocs modifiés
 *   2. Diff mot à mot (Myers) dans chaque bloc modifié
 *   3. Regroupement en « hunks » + catégorisation par critères OBJECTIFS
 */

export const CATEGORY_ORDER = ["chiffres", "formulation", "ajout_suppression", "orthographe", "ponctuation", "mise_en_forme"];

/* ---------- Myers O(ND) générique ---------- */
function myers(a, b) {
  const n = a.length, m = b.length, max = n + m;
  const off = max + 1;
  let v = new Int32Array(2 * max + 3);
  const trace = [];
  outer: for (let d = 0; d <= max; d++) {
    trace.push(v.slice());
    for (let k = -d; k <= d; k += 2) {
      let x = (k === -d || (k !== d && v[off + k - 1] < v[off + k + 1])) ? v[off + k + 1] : v[off + k - 1] + 1;
      let y = x - k;
      while (x < n && y < m && a[x] === b[y]) { x++; y++; }
      v[off + k] = x;
      if (x >= n && y >= m) { trace.push(v.slice()); break outer; }
    }
  }
  // backtrack -> liste d'opérations
  const ops = [];
  let x = n, y = m;
  for (let d = trace.length - 2; d >= 0 && (x > 0 || y > 0); d--) {
    const vv = trace[d];
    const k = x - y;
    const prevK = (k === -d || (k !== d && vv[off + k - 1] < vv[off + k + 1])) ? k + 1 : k - 1;
    const prevX = vv[off + prevK];
    const prevY = prevX - prevK;
    while (x > prevX && y > prevY) { ops.push({ t: "=", i: x - 1, j: y - 1 }); x--; y--; }
    if (d > 0) {
      if (x === prevX) ops.push({ t: "+", j: y - 1 });
      else ops.push({ t: "-", i: x - 1 });
    }
    x = prevX; y = prevY;
  }
  return ops.reverse();
}

/* ---------- Tokenisation ---------- */
function splitLines(text) {
  const out = [];
  let start = 0;
  for (let i = 0; i < text.length; i++) {
    if (text[i] === "\n" || text[i] === "\f") { out.push({ s: text.slice(start, i + 1), start }); start = i + 1; }
  }
  if (start < text.length) out.push({ s: text.slice(start), start });
  return out;
}

// Les nombres (« 48 831 », « 6,2 », « 4,60 ») forment un seul token pour que l'écart porte sur le montant entier.
const TOKEN_RE = /\d{1,3}(?:[ \u00a0\u202f]\d{3})+(?:[.,]\d+)?(?![\p{L}\p{N}])|\d+(?:[.,]\d+)?(?![\p{L}\p{N}])|[\p{L}\p{N}]+|\s+|[^\s\p{L}\p{N}]/gu;
function tokenize(str, base) {
  const out = [];
  for (const m of str.matchAll(TOKEN_RE)) out.push({ s: m[0], start: base + m.index });
  return out;
}

/* ---------- Critères de catégorisation ---------- */
const isWs = (s) => /^\s*$/.test(s);
const stripWs = (s) => s.replace(/\s+/g, "");
const stripPunct = (s) => s.replace(/[^\p{L}\p{N}]/gu, "");
const NUM_RE = /\d{1,3}(?:[ \u00a0\u202f]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?/g;
const digits = (s) => (s.match(NUM_RE) || []).join("|");
const deaccent = (s) => s.normalize("NFD").replace(/\p{Diacritic}/gu, "").toLowerCase();

function levenshtein(a, b) {
  const dp = Array.from({ length: b.length + 1 }, (_, j) => j);
  for (let i = 1; i <= a.length; i++) {
    let prev = dp[0]; dp[0] = i;
    for (let j = 1; j <= b.length; j++) {
      const tmp = dp[j];
      dp[j] = Math.min(dp[j] + 1, dp[j - 1] + 1, prev + (a[i - 1] === b[j - 1] ? 0 : 1));
      prev = tmp;
    }
  }
  return dp[b.length];
}

function looksLikeSpelling(before, after) {
  const wa = before.match(/\p{L}+/gu) || [], wb = after.match(/\p{L}+/gu) || [];
  if (!wa.length || wa.length !== wb.length) return false;
  return wa.every((w, i) => {
    const x = wb[i];
    if (w === x || deaccent(w) === deaccent(x)) return true;
    const d = levenshtein(w.toLowerCase(), x.toLowerCase());
    return d <= 2 && d / Math.max(w.length, x.length) <= 0.34;
  });
}

const visible = (s) => s.replace(/\n/g, "↵").replace(/\f/g, "⇟").replace(/ /g, "·");

export function categorize(before, after) {
  // 1. Mise en forme : seuls les blancs diffèrent
  if (stripWs(before) === stripWs(after)) {
    const nl = (s) => (s.match(/\n/g) || []).length;
    const layout = (s) => s.replace(/[^\S\n]+/g, ""); // texte + retours à la ligne uniquement
    const lb = nl(before) !== nl(after) || layout(before) !== layout(after);
    return {
      category: "mise_en_forme", severity: "info",
      subtype: lb ? "Saut de ligne" : "Espacement",
      rationale: lb
        ? (nl(before) === nl(after)
          ? "Retour à la ligne déplacé : mêmes mots, coupure de ligne différente. Aucun caractère imprimable modifié — remise en page."
          : `Seuls les retours à la ligne diffèrent (${nl(before)} → ${nl(after)}). Aucun caractère imprimable modifié — souvent dû à une remise en page.`)
        : `Seuls les espaces diffèrent (« ${visible(before)} » → « ${visible(after)} »). Aucun caractère imprimable modifié.`,
      confidence: 0.99,
    };
  }
  // 2. Ponctuation : identique une fois ponctuation et blancs retirés
  if (stripPunct(before) === stripPunct(after)) {
    return {
      category: "ponctuation", severity: "faible", subtype: "Ponctuation",
      rationale: "Les lettres et chiffres sont identiques ; seule la ponctuation (virgule, point, tiret…) change.",
      confidence: 0.97,
    };
  }
  // 3. Ajout / suppression pur
  if (isWs(before) || isWs(after)) {
    const added = isWs(before);
    const hasNum = /\d/.test(added ? after : before);
    return {
      category: "ajout_suppression", severity: hasNum ? "elevee" : "moyenne",
      subtype: added ? "Contenu ajouté" : "Contenu supprimé",
      rationale: `Texte ${added ? "présent uniquement dans la nouvelle version" : "présent uniquement dans la version précédente"}.` +
        (hasNum ? " Contient des données chiffrées : à rapprocher des états financiers." : ""),
      confidence: 0.95,
    };
  }
  // 4. Chiffres
  if (/\d/.test(before + after) && digits(before) !== digits(after)) {
    return {
      category: "chiffres", severity: "elevee", subtype: "Montant / donnée chiffrée",
      rationale: `La donnée chiffrée change (${digits(before).replace(/\|/g, " ; ") || "—"} → ${digits(after).replace(/\|/g, " ; ") || "—"}). À rapprocher de la balance / des états financiers.`,
      confidence: 0.98,
    };
  }
  // 5. Orthographe
  if (looksLikeSpelling(before, after)) {
    return {
      category: "orthographe", severity: "faible", subtype: "Correction orthographique",
      rationale: "Mots de même structure à 1-2 caractères près (lettre, accent ou casse) : correction ou faute de frappe probable.",
      confidence: 0.86,
    };
  }
  // 6. Formulation
  return {
    category: "formulation", severity: "moyenne", subtype: "Reformulation",
    rationale: "Des mots différents sont utilisés. Vérifier que le sens et la portée de l'information sont inchangés.",
    confidence: 0.8,
  };
}

/* ---------- Diff principal ---------- */
export function diffDocuments(beforeText, afterText) {
  const la = splitLines(beforeText), lb = splitLines(afterText);
  const lineOps = myers(la.map((l) => l.s), lb.map((l) => l.s));

  // Regroupe les lignes modifiées en blocs (avec positions d'ancrage, utiles si un côté est vide)
  const blocks = [];
  let cur = null, aPos = 0, bPos = 0;
  for (const op of lineOps) {
    if (op.t === "=") {
      if (cur) { blocks.push(cur); cur = null; }
      aPos = la[op.i].start + la[op.i].s.length; bPos = lb[op.j].start + lb[op.j].s.length;
      continue;
    }
    if (!cur) cur = { del: [], ins: [], aStart: aPos, bStart: bPos };
    if (op.t === "-") { cur.del.push(la[op.i]); aPos = la[op.i].start + la[op.i].s.length; }
    else { cur.ins.push(lb[op.j]); bPos = lb[op.j].start + lb[op.j].s.length; }
  }
  if (cur) blocks.push(cur);

  const hunks = [];
  for (const blk of blocks) {
    const aStart = blk.aStart, bStart = blk.bStart;
    const aStr = blk.del.map((l) => l.s).join("");
    const bStr = blk.ins.map((l) => l.s).join("");
    const ta = tokenize(aStr, aStart), tb = tokenize(bStr, bStart);
    const ops = myers(ta.map((t) => t.s), tb.map((t) => t.s));

    let h = null;
    let aPos = aStart, bPos = bStart;
    const flush = () => { if (h) { hunks.push(h); h = null; } };
    for (const op of ops) {
      if (op.t === "=") {
        flush();
        aPos = ta[op.i].start + ta[op.i].s.length;
        bPos = tb[op.j].start + tb[op.j].s.length;
        continue;
      }
      if (!h) h = { aStart: aPos, aEnd: aPos, bStart: bPos, bEnd: bPos };
      if (op.t === "-") { const t = ta[op.i]; h.aEnd = t.start + t.s.length; aPos = h.aEnd; }
      else { const t = tb[op.j]; h.bEnd = t.start + t.s.length; bPos = h.bEnd; }
    }
    flush();
  }

  // Fusionne deux hunks « texte » séparés par un simple espace identique (ex. « selon » → « conformément à »)
  const merged = [];
  for (const h of hunks) {
    const p = merged[merged.length - 1];
    if (p) {
      const gapA = beforeText.slice(p.aEnd, h.aStart), gapB = afterText.slice(p.bEnd, h.bStart);
      const pTxt = !isWs(beforeText.slice(p.aStart, p.aEnd) + afterText.slice(p.bStart, p.bEnd));
      const hTxt = !isWs(beforeText.slice(h.aStart, h.aEnd) + afterText.slice(h.bStart, h.bEnd));
      if (pTxt && hTxt && gapA === gapB && /^ $/.test(gapA)) {
        p.aEnd = h.aEnd; p.bEnd = h.bEnd; continue;
      }
    }
    merged.push({ ...h });
  }

  // Retour à la ligne déplacé (« actifs↵et passifs » → « actifs et↵passifs ») : deux hunks voisins dont le
  // contenu imprimable est identique une fois réunis => un seul écart de mise en forme.
  for (let k = 0; k < merged.length - 1; k++) {
    const h = merged[k], n = merged[k + 1];
    const aS = Math.min(h.aStart, n.aStart), aE = Math.max(h.aEnd, n.aEnd);
    const bS = Math.min(h.bStart, n.bStart), bE = Math.max(h.bEnd, n.bEnd);
    if (aE - aS > 80 || bE - bS > 80) continue;
    const b = beforeText.slice(aS, aE), a = afterText.slice(bS, bE);
    if (stripWs(b) === stripWs(a) && b !== a) { Object.assign(h, { aStart: aS, aEnd: aE, bStart: bS, bEnd: bE }); merged.splice(k + 1, 1); }
  }

  // Retire les blancs communs en bordure (« selon␣ » / « conformément à␣ » → « selon » / « conformément à »)
  for (const h of merged) {
    while (h.aEnd > h.aStart && h.bEnd > h.bStart && /\s/.test(beforeText[h.aEnd - 1]) && beforeText[h.aEnd - 1] === afterText[h.bEnd - 1]
      && !isWs(beforeText.slice(h.aStart, h.aEnd - 1) + afterText.slice(h.bStart, h.bEnd - 1))) { h.aEnd--; h.bEnd--; }
    while (h.aEnd > h.aStart && h.bEnd > h.bStart && /\s/.test(beforeText[h.aStart]) && beforeText[h.aStart] === afterText[h.bStart]
      && !isWs(beforeText.slice(h.aStart + 1, h.aEnd) + afterText.slice(h.bStart + 1, h.bEnd))) { h.aStart++; h.bStart++; }
  }

  return merged.map((h, idx) => {
    const before = beforeText.slice(h.aStart, h.aEnd);
    const after = afterText.slice(h.bStart, h.bEnd);
    const cat = categorize(before, after);
    return {
      id: `d${String(idx + 1).padStart(3, "0")}`,
      ...cat,
      before, after,
      beforeRange: [h.aStart, h.aEnd],
      afterRange: [h.bStart, h.bEnd],
      page: pageAt(afterText, h.bStart),
      section: sectionAt(afterText, h.bStart),
      context: contextAt(afterText, h.bStart, h.bEnd),
    };
  });
}

export function pageAt(text, offset) {
  let p = 1;
  for (let i = 0; i < offset && i < text.length; i++) if (text[i] === "\f") p++;
  return p;
}

export function sectionAt(text, offset) {
  // Titres de type « 4.3 Bilan… », « 1.b.3 Règles… », « Note 2 … » ou « 2. Chiffres clés »
  const RE = /^\s*((?:Note\s+)?\d+(?:\.[0-9a-z]+)*\.?)\s+(\p{Lu}[^\t\n]{2,})$/u;
  const lines = text.slice(0, offset).split(/[\n\f]/);
  for (let i = lines.length - 1; i >= 0; i--) {
    // Numéro seul sur sa ligne (titre composé en deux blocs) : le titre est la ligne suivante non vide
    const lone = lines[i].match(/^\s*(\d+(?:\.[0-9a-z]+)+)\s*$/);
    if (lone) {
      const next = lines.slice(i + 1).find((l) => l.trim());
      if (next && /^\p{Lu}/u.test(next.trim())) return `§${lone[1]} ${next.trim().slice(0, 38)}`;
    }
    const m = lines[i].match(RE);
    if (m && !/\d+[ \u00a0]\d{3}|\t/.test(m[2])) {
      const t = m[2].replace(/\s*\(.*$/, "").trim();
      return `§${m[1].replace(/\.$/, "")} ${t.length > 38 ? t.slice(0, 37) + "…" : t}`;
    }
  }
  return "En-tête";
}

function contextAt(text, s, e) {
  const a = Math.max(0, s - 45), b = Math.min(text.length, e + 45);
  return (a > 0 ? "…" : "") + text.slice(a, b).replace(/[\n\f]+/g, " ") + (b < text.length ? "…" : "");
}
