/** Référentiels : dossiers clients (démo) et catégories d'écarts. */

export const CLIENTS = [
  { id: "bnp", name: "BNP Paribas", short: "BNP", sector: "Banque", mission: "Audit légal — Exercice 2025", doc: "Document d'enregistrement universel 2025", phase: "Phase finale", hue: "#00915A" },
  { id: "loreal", name: "L'Oréal", short: "LO", sector: "Cosmétiques", mission: "Audit légal — Exercice 2025", doc: "Document d'enregistrement universel 2025", phase: "Phase finale", hue: "#B08D57" },
  { id: "orange", name: "Orange", short: "OR", sector: "Télécommunications", mission: "Audit légal — Exercice 2025", doc: "Document d'enregistrement universel 2025", phase: "Intérim", hue: "#FF7900" },
  { id: "socgen", name: "Société Générale", short: "SG", sector: "Banque", mission: "Audit légal — Exercice 2025", doc: "Rapport financier annuel 2025", phase: "Phase finale", hue: "#E9041E" },
  { id: "kering", name: "Kering", short: "KER", sector: "Luxe", mission: "Audit légal — Exercice 2025", doc: "Document d'enregistrement universel 2025", phase: "Planification", hue: "#6B6B6B" },
];

/** Catégories : critères OBJECTIFS, ordre = priorité de revue. */
export const CATEGORIES = {
  chiffres: {
    label: "Écarts de chiffres", short: "Chiffres", color: "#E5484D",
    rule: "Un montant, un pourcentage, une date ou un effectif diffère.",
  },
  formulation: {
    label: "Modifications de formulation", short: "Formulation", color: "#3E63DD",
    rule: "Des mots différents sont employés ; le sens peut changer.",
  },
  ajout_suppression: {
    label: "Ajouts / suppressions", short: "Ajout/Suppr.", color: "#0D9488",
    rule: "Texte présent dans une seule des deux versions.",
  },
  orthographe: {
    label: "Corrections orthographiques", short: "Orthographe", color: "#8E4EC6",
    rule: "Même mot à 1-2 caractères près (lettre, accent, casse).",
  },
  ponctuation: {
    label: "Ponctuation", short: "Ponctuation", color: "#D97706",
    rule: "Seule la ponctuation change (virgule, point, tiret…).",
  },
  mise_en_forme: {
    label: "Espaces & sauts de ligne", short: "Mise en forme", color: "#D6409F",
    rule: "Seuls des espaces ou retours à la ligne diffèrent.",
  },
};

export const SEVERITY = {
  elevee: { label: "Élevée", rank: 3 },
  moyenne: { label: "Moyenne", rank: 2 },
  faible: { label: "Faible", rank: 1 },
  info: { label: "Info", rank: 0 },
};
