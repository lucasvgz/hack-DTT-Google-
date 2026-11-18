/**
 * Stockage local des PDF (IndexedDB) pour réafficher les vraies pages pendant le pointage et dans la synthèse.
 * Mode démo uniquement : en production, les PDF restent côté serveur (URL signées à durée courte).
 */
const DB = "tickmark", STORE = "pdfs";
let dbp = null;
const mem = new Map(); // repli si IndexedDB est indisponible (navigation privée)

function open() {
  if (!dbp) {
    dbp = new Promise((resolve, reject) => {
      try {
        const r = indexedDB.open(DB, 1);
        r.onupgradeneeded = () => r.result.createObjectStore(STORE);
        r.onsuccess = () => resolve(r.result);
        r.onerror = () => reject(r.error);
      } catch (e) { reject(e); }
    });
  }
  return dbp;
}

async function tx(mode, fn) {
  const db = await open();
  return new Promise((resolve, reject) => {
    const t = db.transaction(STORE, mode);
    const req = fn(t.objectStore(STORE));
    t.oncomplete = () => resolve(req?.result);
    t.onerror = () => reject(t.error);
  });
}

export async function putPdf(key, buffer) {
  mem.set(key, buffer);
  try { await tx("readwrite", (s) => s.put(buffer, key)); } catch { /* mémoire seule */ }
}

export async function getPdf(key) {
  if (mem.has(key)) return mem.get(key);
  try { const v = await tx("readonly", (s) => s.get(key)); if (v) mem.set(key, v); return v || null; } catch { return null; }
}

export async function clearPdfs() {
  mem.clear();
  try { await tx("readwrite", (s) => s.clear()); } catch { /* ignore */ }
}
