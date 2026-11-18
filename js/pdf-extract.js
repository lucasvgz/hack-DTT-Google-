/**
 * Extraction du texte d'un PDF dans le navigateur (pdf.js, embarqué dans /vendor — aucun CDN tiers).
 * Reconstruit les lignes et les paragraphes à partir des positions (x, y) des fragments de texte.
 * Les pages sont séparées par le caractère \f (form feed), utilisé par l'UI pour paginer.
 */
let pdfjsPromise = null;
async function getPdfjs() {
  if (!pdfjsPromise) {
    pdfjsPromise = import("../vendor/pdfjs/pdf.min.mjs").then((lib) => {
      lib.GlobalWorkerOptions.workerSrc = new URL("../vendor/pdfjs/pdf.worker.min.mjs", import.meta.url).href;
      return lib;
    });
  }
  return pdfjsPromise;
}

export async function extractPdfText(arrayBuffer, pdfjsLib) {
  const lib = pdfjsLib || (await getPdfjs());
  const pdf = await lib.getDocument({ data: new Uint8Array(arrayBuffer), isEvalSupported: false }).promise;
  const pages = [];
  for (let p = 1; p <= pdf.numPages; p++) {
    const page = await pdf.getPage(p);
    const content = await page.getTextContent();
    pages.push(itemsToText(content.items));
  }
  return { text: pages.join("\f"), pageCount: pdf.numPages };
}

export function itemsToText(items) {
  const frags = items
    .filter((it) => typeof it.str === "string" && it.str.length)
    .map((it) => ({ str: it.str, x: it.transform[4], y: it.transform[5], w: it.width, h: Math.abs(it.transform[3]) || it.height || 10 }));
  if (!frags.length) return "";

  // Regroupe par ligne (tolérance verticale = 40 % de la hauteur de police)
  frags.sort((a, b) => b.y - a.y || a.x - b.x);
  const lines = [];
  for (const f of frags) {
    const last = lines[lines.length - 1];
    if (last && Math.abs(last.y - f.y) <= f.h * 0.4) last.items.push(f);
    else lines.push({ y: f.y, h: f.h, items: [f] });
  }

  // Interligne de référence = médiane des écarts
  const gaps = [];
  for (let i = 1; i < lines.length; i++) gaps.push(lines[i - 1].y - lines[i].y);
  const sorted = [...gaps].sort((a, b) => a - b);
  const median = sorted.length ? sorted[Math.floor(sorted.length / 2)] : 0;

  let out = "";
  lines.forEach((line, i) => {
    line.items.sort((a, b) => a.x - b.x);
    let s = "";
    line.items.forEach((it, j) => {
      if (j > 0) {
        const prev = line.items[j - 1];
        const gap = it.x - (prev.x + prev.w);
        if (gap > it.h * 0.2 && !/\s$/.test(s) && !/^\s/.test(it.str)) s += " ";
      }
      s += it.str;
    });
    if (i > 0) {
      const gap = lines[i - 1].y - line.y;
      // Écart > 1,5 interligne => ligne(s) vide(s) = saut de paragraphe
      const blank = median > 0 ? Math.max(0, Math.round(gap / median) - 1) : 0;
      out += "\n" + "\n".repeat(Math.min(blank, 3));
    }
    out += s;
  });
  return out;
}
