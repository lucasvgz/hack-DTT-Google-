# Tickmark : pointage IA des documents d'audit

> Hackathon Deloitte × Google Cloud, 2026 · Métier : **Audit** · Brique : **UI (front-end)**

Tickmark compare deux versions d'un document (ex. URD N-1 et N), repère **tous** les écarts, les **catégorise selon des critères objectifs** et guide l'auditeur dans le pointage jusqu'à une synthèse envoyée au client.

```
Accueil (dossiers clients) → Dépôt N-1 / N → Analyse par l'agent → Tableau de bord des écarts
→ Pointage (liste | documents côte à côte | décision) → Finalisation → Synthèse → Portail client
```

## Démarrer en 30 secondes

Aucune installation et aucun build : HTML, CSS et JS natifs (modules ES).

```bash
git clone <repo> && cd tickmark
python3 -m http.server 8000      # ou : npx serve .
# ouvrir http://localhost:8000
```

> ⚠️ Ne pas ouvrir `index.html` en double-cliquant (`file://`) : les modules ES et `crypto.subtle` exigent un serveur HTTP (ou HTTPS).

Pour la démo : **BNP Paribas → « Utiliser les documents de démonstration » → Lancer l'analyse**.

- `samples/urd_v1.pdf` : 10 pages réelles de l'URD 2025 de BNP Paribas (chapitre 4 « États financiers consolidés », pages 200 à 209 ; document public).
- `samples/urd_v2.pdf` : le même extrait, modifié à la main directement dans le flux PDF (mêmes polices, même mise en page) avec 13 écarts : 6 chiffres, 2 fautes d'orthographe, 2 ponctuations, 1 reformulation, 1 suppression, 1 saut de ligne déplacé. Le corrigé est dans `tools/make_urd_v2.py`.
- Pendant le pointage, les **vraies pages PDF** sont affichées (rendu pdf.js) et les écarts sont surlignés par-dessus. Le zoom se règle dans la barre d'outils.

## Déployer sur GitHub Pages

1. Pousser le dossier sur un repo GitHub (branche `main`).
2. **Settings → Pages → Source : GitHub Actions**. Le workflow `.github/workflows/pages.yml` déploie à chaque push.
3. L'app est servie en HTTPS sur `https://<org>.github.io/<repo>/`.

## Brancher le back-end (merge avec l'équipe)

Le seul point de contact est **`js/api.js`**, configuré par **`js/config.js`** :

```js
API_BASE_URL: ""                              // mode démo : tout tourne dans le navigateur
API_BASE_URL: "https://tickmark-xxx.run.app"  // mode réel : appelle l'agent sur GCP
```

On peut aussi tester sans toucher au code : `https://…/index.html?api=https://tickmark-xxx.run.app`.

Le format attendu (endpoints, JSON, offsets de surlignage, catégories) est décrit dans **[`docs/API_CONTRACT.md`](docs/API_CONTRACT.md)**. Le moteur local `js/diff-engine.js` produit déjà ce format : c'est l'implémentation de référence que le back-end peut porter en Python, puis enrichir avec Gemini.

## Arborescence

```
index.html              Point d'entrée (CSP stricte, aucun CDN)
css/styles.css          Design system (ADN Deloitte : noir = cadre, vert #86BC25 = signal)
js/config.js            ← URL de l'API, utilisateur, délais
js/api.js               ← Couche back-end (remote | local)
js/diff-engine.js       Moteur local : diff Myers ligne puis mot, catégorisation par règles
js/pdf-extract.js       Extraction du texte PDF + carte de positions (pdf.js embarqué)
js/pdf-view.js          Rendu des vraies pages PDF avec surlignage des écarts
js/blobstore.js         Stockage local des PDF (IndexedDB, mode démo)
js/data.js              Dossiers clients et catégories (couleurs, règles)
js/store.js             État et persistance localStorage (mode démo)
js/app.js               Routeur et vues
js/demo-docs.js         Textes de démo (généré)
vendor/                 pdf.js 4.10 et polices Inter / JetBrains Mono (hébergés localement)
samples/                urd_v1.pdf / urd_v2.pdf (extrait URD 2025 BNP Paribas, V2 modifiée)
tools/                  make_urd_v2.py (génère la paire de démo) · test-engine.mjs · generate_samples.py (texte de repli)
docs/API_CONTRACT.md    Contrat front ↔ back et exigences sécurité
```

## Les 3 dimensions du hack

| Dimension | Dans l'UI |
|---|---|
| **Métier (Audit)** | Pointage de fin de mission : comparaison exhaustive N-1 / N, navigation façon Ctrl+F (↑ ↓ / Entrée), décision par écart (✕ pas une erreur, ou note puis validation), écartement en masse des écarts de mise en forme, finalisation attestée, synthèse annotée, envoi au client |
| **Agent IA** | Détection, catégorisation en 6 classes objectives, justification (`rationale`) et niveau de confiance par écart, sévérité |
| **Sécurité intégrée** | Mode local sans aucune transmission · CSP stricte sans dépendance tierce · contrôle de la signature PDF et de la taille · empreintes SHA-256 (preuve d'intégrité, visibles aussi côté client) · journal d'audit horodaté · double attestation (finalisation, envoi) · partage client limité aux erreurs confirmées · verrouillage après 15 min d'inactivité · fichiers bruts jamais persistés |

## Raccourcis clavier (écran de pointage)

| Touche | Action |
|---|---|
| `↓` / `Entrée` / `J` | Écart suivant (boucle comme Ctrl+F) |
| `↑` / `Maj+Entrée` / `K` | Écart précédent |
| `X` | Pas une erreur |
| `N` | Écrire une note |
| `Ctrl/⌘ + Entrée` | Valider l'écart (erreur confirmée et note) |

## Limites connues (mode démo)

- L'extraction PDF côté navigateur lit la couche texte : un PDF scanné renverra un texte vide (OCR à prévoir côté back-end, Document AI). pdf.js fusionne les espaces multiples : un double espace dans un PDF n'est donc pas détectable côté navigateur (les sauts de ligne déplacés, eux, le sont).
- Un écart de remise en page (retour à la ligne déplacé) est classé « Espaces & sauts de ligne » : c'est voulu, et ces écarts s'écartent en masse.
- Le portail client est simulé dans le même navigateur (localStorage). En production, il s'appuie sur `POST /send` et un contrôle d'accès côté serveur.
- Les dossiers clients sont des exemples (`js/data.js`) et les documents sont fictifs.
