/**
 * Configuration front — le seul fichier à modifier pour brancher le back-end.
 *
 *  API_BASE_URL = ""  -> MODE DÉMO : extraction PDF + diff + catégorisation 100 % dans le navigateur
 *                        (aucune donnée ne quitte le poste). Idéal pour la démo du hackathon.
 *  API_BASE_URL = "https://<service>.run.app" -> l'UI appelle le back-end (agent IA sur GCP),
 *                        voir docs/API_CONTRACT.md pour le format attendu.
 *
 *  Surcharge possible sans toucher au code : ?api=https://... dans l'URL (stocké en session).
 */
const params = new URLSearchParams(location.search);
let fromSession = null;
try {
  const apiParam = params.get("api");
  if (apiParam === "local" || apiParam === "demo") {
    sessionStorage.removeItem("tickmark.api");
  } else if (apiParam) {
    sessionStorage.setItem("tickmark.api", apiParam);
  }
  fromSession = sessionStorage.getItem("tickmark.api");
} catch { /* stockage indisponible */ }

const isServedByBackend =
  ((location.hostname === "localhost" || location.hostname === "127.0.0.1") && location.port === "8000") ||
  location.hostname.endsWith(".run.app");

const defaultApiBaseUrl =
  params.get("api") === "demo" ? "" : (fromSession || (isServedByBackend ? location.origin : ""));

export const CONFIG = {
  APP_NAME: "Tickmark",
  APP_TAGLINE: "Pointage IA",
  API_BASE_URL: defaultApiBaseUrl,
  USER: { firstName: "Lucas", lastName: "Giovinazzo", role: "Auditeur — Senior", initials: "LG" },
  // Bloque l'UI après X minutes d'inactivité (sécurité). 0 = désactivé.
  IDLE_LOCK_MINUTES: 15,
  // Délai minimal d'affichage des étapes d'analyse en mode démo (ms), pour la lisibilité du pitch.
  DEMO_STEP_MS: 650,
  MAX_FILE_MB: 50,
};
