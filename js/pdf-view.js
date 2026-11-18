/**
 * Affichage des VRAIES pages PDF (rendu pdf.js sur canvas) avec les écarts surlignés par-dessus.
 * Les surlignages sont positionnés grâce à la carte de positions (layout) produite à l'extraction.
 */
import { getPdfjs } from "./pdf-extract.js";
import { getPdf } from "./blobstore.js";

const docs = new Map();

export function loadDoc(key) {
  if (!docs.has(key)) {
    docs.set(key, (async () => {
      const buf = await getPdf(key);
      if (!buf) return null;
      const lib = await getPdfjs();
      return lib.getDocument({ data: new Uint8Array(buf.slice(0)), isEvalSupported: false }).promise;
    })());
  }
  return docs.get(key);
}

export async function hasPdf(key) { return Boolean(await getPdf(key)); }

/** Boîtes (en % de la page) couvrant la plage [s, e) du texte. */
function boxesFor(page, s, e) {
  const out = [];
  for (const [fs, fe, x, y, w, h] of page.f) {
    if (fe <= s || fs >= e || fe === fs) continue;
    const len = fe - fs;
    const a = Math.max(s, fs) - fs, b = Math.min(e, fe) - fs;
    out.push({ x: x + (w * a) / len, x1: x + (w * b) / len, y, h });
  }
  // Fusionne les boîtes contiguës d'une même ligne
  const merged = [];
  for (const bx of out) {
    const p = merged[merged.length - 1];
    if (p && Math.abs(p.y - bx.y) < bx.h * 0.4 && bx.x - p.x1 < bx.h * 1.2) { p.x1 = Math.max(p.x1, bx.x1); continue; }
    merged.push({ ...bx });
  }
  return merged;
}

/** Position d'un curseur (insertion / suppression) à l'offset `o`. */
function caretAt(page, o) {
  let best = null;
  for (const [fs, fe, x, y, w, h] of page.f) {
    if (fe === fs) continue;
    if (o >= fs && o <= fe) return { x: x + (w * (o - fs)) / (fe - fs), y, h };
    if (fe <= o && (!best || fe > best.fe)) best = { fe, x: x + w, y, h };
  }
  return best;
}

const pct = (v, total) => `${((v / total) * 100).toFixed(3)}%`;

/**
 * HTML des pages (sans le rendu canvas, fait ensuite par attach()).
 * @param layout  { pages:[{w,h,f}] }
 * @param diffs   écarts à surligner
 * @param side    "before" | "after"
 * @param opts    { activeId, numbered: Map, color(cat) }
 */
export function pagesHtml(layout, diffs, side, opts) {
  const perPage = layout.pages.map(() => []);
  for (const d of diffs) {
    const [s, e] = side === "before" ? d.beforeRange : d.afterRange;
    layout.pages.forEach((pg, pi) => {
      if (!pg.f.length) return;
      const first = pg.f[0][0], last = pg.f[pg.f.length - 1][1];
      if (e < first || s > last + 1) return;
      if (e > s) {
        const bxs = boxesFor(pg, s, e);
        if (bxs.length) perPage[pi].push({ d, bxs });
        else { const c = caretAt(pg, s); if (c) perPage[pi].push({ d, caret: c }); }
      } else {
        const c = caretAt(pg, s);
        if (c) perPage[pi].push({ d, caret: c });
      }
    });
  }
  return layout.pages.map((pg, pi) => {
    const marks = perPage[pi].map(({ d, bxs, caret }) => {
      const cls = `${d.status || "pending"}${d.id === opts.activeId ? " active" : ""}`;
      const style = `--c:${opts.color(d.category)}`;
      const n = opts.numbered?.get(d.id);
      if (caret) {
        return `<span class="pbox caret ${cls}" data-id="${d.id}" style="${style};left:${pct(caret.x - 1, pg.w)};top:${pct(pg.h - caret.y - caret.h * 0.85, pg.h)};height:${pct(caret.h * 1.1, pg.h)}" title="${d.id}">${n ? `<b class="badge-n">${n}</b>` : ""}</span>`;
      }
      return bxs.map((b, k) => `<span class="pbox ${cls}" data-id="${d.id}" style="${style};left:${pct(b.x - 1, pg.w)};top:${pct(pg.h - b.y - b.h * 0.85, pg.h)};width:${pct(Math.max(2.5, b.x1 - b.x + 2), pg.w)};height:${pct(b.h * 1.15, pg.h)}" title="${d.id}">${n && k === bxs.length - 1 ? `<b class="badge-n">${n}</b>` : ""}</span>`).join("");
    }).join("");
    return `<div class="pdfpage" data-page="${pi}" style="aspect-ratio:${pg.w}/${pg.h}"><canvas></canvas><div class="pmarks">${marks}</div><span class="sheet-no">p. ${pi + 1}</span></div>`;
  }).join("");
}

/** Rend les canvas des pages visibles (paresseux) dans `container`. */
export function attach(container, key) {
  const rendered = new WeakSet();
  const io = new IntersectionObserver(async (entries) => {
    const doc = await loadDoc(key);
    if (!doc) return;
    for (const en of entries) {
      if (!en.isIntersecting || rendered.has(en.target)) continue;
      rendered.add(en.target);
      const el = en.target;
      const page = await doc.getPage(Number(el.dataset.page) + 1);
      const base = page.getViewport({ scale: 1 });
      const cssW = el.clientWidth || 600;
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const vp = page.getViewport({ scale: Math.min((cssW / base.width) * dpr * 1.25, 4000 / base.width) });
      const canvas = el.querySelector("canvas");
      canvas.width = Math.floor(vp.width); canvas.height = Math.floor(vp.height);
      await page.render({ canvasContext: canvas.getContext("2d"), viewport: vp }).promise;
      el.classList.add("ready");
    }
  }, { root: container, rootMargin: "600px 0px" });
  container.querySelectorAll(".pdfpage").forEach((p) => io.observe(p));
  return () => io.disconnect();
}
