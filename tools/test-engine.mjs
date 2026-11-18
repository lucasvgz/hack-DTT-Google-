// Test rapide du moteur local : node tools/test-engine.mjs
import { diffDocuments } from "../js/diff-engine.js";
import { DEMO_BEFORE, DEMO_AFTER } from "../js/demo-docs.js";

const diffs = diffDocuments(DEMO_BEFORE, DEMO_AFTER);
let ok = true;
for (const d of diffs) {
  const b = DEMO_BEFORE.slice(...d.beforeRange), a = DEMO_AFTER.slice(...d.afterRange);
  if (b !== d.before || a !== d.after) { ok = false; console.error("Offsets incohérents", d.id); }
  console.log(d.id, d.category.padEnd(18), JSON.stringify(d.before), "→", JSON.stringify(d.after));
}
console.log(`\n${diffs.length} écarts · offsets ${ok ? "OK" : "KO"}`);
process.exit(ok ? 0 : 1);
