/**
 * Extraction du texte d'un PDF dans le navigateur (pdf.js, embarqué dans /vendor — aucun CDN tiers).
 * Reconstruit les lignes et les paragraphes à partir des positions (x, y) des fragments de texte.
 *
 * Renvoie aussi une « carte de positions » (layout) : pour chaque fragment de texte, sa plage de caractères
 * dans le texte extrait et sa boîte sur la page. L'UI s'en sert pour surligner les écarts DIRECTEMENT
 * sur le rendu des vraies pages PDF.
 * Les pages sont séparées par le caractère \f (form feed).
 */
let pdfjsPromise = null;
export async function getPdfjs() {
  if (!pdfjsPromise) {
    pdfjsPromise = import("../vendor/pdfjs/pdf.min.mjs").then((lib) => {
      lib.GlobalWorkerOptions.workerSrc = new URL("../vendor/pdfjs/pdf.worker.min.mjs", import.meta.url).href;
      return lib;
    });
  }
  return pdfjsPromise;
}

const r1 = (v) => Math.round(v * 10) / 10;

/**
 * @returns {{text:string, pageCount:number, layout:{pages:Array<{w:number,h:number,f:Array<[number,number,number,number,number,number]>}>}}}
 *   f = [début, fin, x, y (ligne de base, origine en bas), largeur, corps] — offsets relatifs au texte complet
 */
export async function extractPdfText(arrayBuffer, pdfjsLib) {
  const lib = pdfjsLib || (await getPdfjs());
  const pdf = await lib.getDocument({ data: new Uint8Array(arrayBuffer), isEvalSupported: false }).promise;
  let text = "";
  const pages = [];
  for (let p = 1; p <= pdf.numPages; p++) {
    const page = await pdf.getPage(p);
    const content = await page.getTextContent();
    const [vx, vy, vx1, vy1] = page.view;
    if (p > 1) text += "\f";
    const base = text.length;
    const res = itemsToText(content.items);
    text += res.text;
    pages.push({
      w: r1(vx1 - vx), h: r1(vy1 - vy),
      f: res.frags.map((f) => [base + f.s, base + f.e, r1(f.x - vx), r1(f.y - vy), r1(f.w), r1(f.h)]),
    });
  }
  return { text, pageCount: pdf.numPages, layout: { pages } };
}

export function itemsToText(items) {
  const frags = items
    .filter((it) => typeof it.str === "string" && it.str.trim().length) // les blancs sont recalculés à partir des écarts horizontaux
    .map((it) => ({ str: it.str, x: it.transform[4], y: it.transform[5], w: it.width, h: Math.abs(it.transform[3]) || it.height || 10 }));
  if (!frags.length) return { text: "", frags: [] };

  // Regroupe en lignes en conservant l'ordre du flux PDF : les mises en page à deux colonnes
  // (notes annexes) sont ainsi lues colonne par colonne, et non ligne à ligne à travers la page.
  const lines = [];
  const sameY = (l, f) => Math.abs(l.y - f.y) <= f.h * 0.4;
  for (const f of frags) {
    const last = lines[lines.length - 1];
    // 1) suite naturelle de la ligne en cours (cellules de tableau, mots suivants)
    let target = last && sameY(last, f) && f.x >= last.maxX - f.h * 0.6 ? last : null;
    // 2) fragment ajouté plus loin dans le flux (PDF modifié a posteriori) mais situé DANS une ligne existante
    if (!target) target = lines.find((l) => sameY(l, f) && f.x >= l.minX - f.h * 0.3 && f.x <= l.maxX + f.h * 0.8) || null;
    if (target) {
      target.items.push(f); target.maxX = Math.max(target.maxX, f.x + f.w); target.minX = Math.min(target.minX, f.x);
    } else lines.push({ y: f.y, h: f.h, items: [f], minX: f.x, maxX: f.x + f.w });
  }

  // Interligne de référence = médiane des écarts
  const gaps = [];
  for (let i = 1; i < lines.length; i++) { const g = lines[i - 1].y - lines[i].y; if (g > 0) gaps.push(g); }
  const sorted = [...gaps].sort((a, b) => a - b);
  const median = sorted.length ? sorted[Math.floor(sorted.length / 2)] : 0;

  let out = "";
  const placed = [];
  lines.forEach((line, i) => {
    line.items.sort((a, b) => a.x - b.x);
    let s = "";
    const local = [];
    line.items.forEach((it, j) => {
      if (j > 0) {
        const prev = line.items[j - 1];
        const gap = it.x - (prev.x + prev.w);
        // Grand écart = changement de cellule de tableau : tabulation (évite de fusionner « 211 330 » et « 182 496 »)
        if (gap > it.h * 1.5) s = s.replace(/\s+$/, "") + "\t";
        else if (gap > it.h * 0.2 && !/\s$/.test(s) && !/^\s/.test(it.str)) s += " ";
      }
      local.push({ s: s.length, e: s.length + it.str.length, x: it.x, y: it.y, w: it.w, h: it.h });
      s += it.str;
    });
    if (i > 0) {
      const gap = lines[i - 1].y - line.y;
      // Écart > 1,5 interligne => ligne(s) vide(s) = saut de paragraphe ; remontée dans la page = nouvelle colonne
      const blank = gap <= 0 ? 1 : median > 0 ? Math.max(0, Math.round(gap / median) - 1) : 0;
      out += "\n" + "\n".repeat(Math.min(blank, 3));
    }
    const base = out.length;
    const trimmed = s.replace(/[ \t]+$/, "");
    out += trimmed;
    for (const f of local) placed.push({ ...f, s: base + Math.min(f.s, trimmed.length), e: base + Math.min(f.e, trimmed.length) });
  });
  return { text: out, frags: placed };
}
