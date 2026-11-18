# URD Verifier Agent — Vérification V0 vs V1 & Human-in-the-Loop

Système agentique complet développé à partir de zéro pour comparer et vérifier les Documents d'Enregistrement Universel (**URD**) d'entreprise (**V0**, **V1**, et optionnellement **URD N-1**), classifier l'ensemble des différences (**forme, contenu, chiffrage, structure, métadonnées, réglementaire/ESEF, visuel/graphique**), exécuter les **15 contrôles de la taxonomie URD**, localiser chaque anomalie au pixel près (**bounding boxes PDF**) et gérer la revue **Human-in-the-Loop (HITL)** via API REST pour l'UI.

---

## Architecture du Projet

```
urd-verifier-agent/
├── pyproject.toml
├── .env.example
├── scripts/
│   └── generate_sample_urds.py          # Génère des PDF URD V0, V1 et N-1 réalistes avec les 15 types d'erreurs
├── src/urd_verifier/
│   ├── config.py                        # Tolérances, seuils de matérialité, fournisseur LLM (Gemini/OpenAI/Anthropic/Offline)
│   ├── cli.py                           # CLI Typer/Rich (`verify`, `serve`)
│   ├── models/
│   │   ├── document.py                  # BoundingBox, TextSpan, TextBlock, TableData, ChartFigure, ParsedPDF
│   │   ├── findings.py                  # DiffCategory, ControlType (15 contrôles), Finding, LocationRef, AuditAction
│   │   └── session.py                   # VerificationSession, VersionDetectionResult, HITLDecisionRequest
│   ├── ingestion/
│   │   ├── pdf_parser.py                # Extraction hybride pdfplumber + PyMuPDF (styles, tableaux, renvois, graphiques)
│   │   ├── number_parser.py             # Parsing financier FR/EN (`1 234,5 M€`, `(45,2)`, `+4,2 %`, `k€`, `Md€`)
│   │   └── version_detector.py          # Identification automatique V0 / V1 / URD N-1 avec score de confiance
│   ├── diff_engine/
│   │   ├── aligner.py                   # Alignement robuste blocs & tableaux même avec décalage de pages
│   │   ├── text_diff.py                 # Diff texte, chiffres en prose et forme typographique (police, taille, gras, couleur)
│   │   ├── table_diff.py                # Diff cellule par cellule, en-têtes, unités et inversion de colonnes
│   │   └── classifier.py                # Raffinement taxonomie URD, matérialité et routage HITL
│   ├── checks/
│   │   ├── deterministic.py             # Contrôles 1 à 6 (100 % Automatisables)
│   │   ├── ai_semantic.py               # Contrôles 7 à 11 (Semi-automatisables IA + Vision + Humain)
│   │   └── human_mandatory.py           # Contrôles 12 à 15 (Human Check obligatoire)
│   ├── agent/
│   │   ├── llm_client.py                # Client unifié Gemini / OpenAI / Anthropic + fallback déterministe offline
│   │   ├── orchestrator.py              # Pipeline agentique complet
│   │   └── hitl.py                      # Machine à états HITL & piste d'audit immuable
│   ├── export/
│   │   ├── pdf_annotator.py             # Surlignage couleur + notes intégrées sur copies V0 et V1
│   │   └── report.py                    # Métriques SessionSummary & rapport exécutif Markdown
│   ├── storage/session_store.py         # Persistance disque JSON par session
│   └── api/
│       ├── main.py                      # Application FastAPI + CORS
│       └── routes.py                    # Contrat API REST complet pour l'UI
└── tests/                               # Suite pytest complète (unitaire, E2E 15 contrôles, API REST)
```

---

## Démarrage Rapide

```bash
cd /Users/paulbriand/.gemini/antigravity/scratch/urd-verifier-agent

# 1. Activer l'environnement virtuel
source .venv/bin/activate

# 2. (Optionnel) Configurer une clé LLM pour la couche sémantique & Vision avancée
cp .env.example .env
# Renseigner GEMINI_API_KEY, OPENAI_API_KEY ou ANTHROPIC_API_KEY
# Sans clé API, le moteur déterministe + heuristique offline fonctionne à 100 %.

# 3. Générer des PDF URD de test (V0, V1, URD N-1)
python scripts/generate_sample_urds.py

# 4. Lancer la vérification via CLI
python -m urd_verifier.cli verify sample_data/URD_2025_V0_Brouillon.pdf sample_data/URD_2025_V1_Amende.pdf sample_data/URD_2024_Publie.pdf --json sample_data/result.json

# 5. Démarrer le serveur API pour l'UI de votre collègue
python -m urd_verifier.cli serve --host 0.0.0.0 --port 8000
# Documentation OpenAPI interactive : http://localhost:8000/docs
```

---

## Contrat d'Intégration UI (FastAPI `/api/v1`)

| Méthode & Route | Rôle pour l'UI |
|---|---|
| `GET /api/v1/health` | État du backend & fournisseur LLM actif |
| `GET /api/v1/taxonomy` | Liste des catégories de diff, des 15 types de contrôles, niveaux d'automatisation et statuts HITL |
| `POST /api/v1/sessions/verify` | Upload multipart de 2+ PDF (`files`) -> détection V0/V1 + vérification complète (`?run_async=true` pour mode asynchrone) |
| `POST /api/v1/sessions/verify-local` | Lancement depuis chemins locaux |
| `GET /api/v1/sessions/{id}` | État complet de la session, confiance V0/V1, résumé, trace agentique et findings |
| `POST /api/v1/sessions/{id}/versions/confirm` | **HITL Version** : confirmer ou inverser V0 / V1 / URD N-1 et relancer |
| `GET /api/v1/sessions/{id}/findings` | Filtrer les écarts (`diff_category`, `control_type`, `severity`, `hitl_status`, `page`, `requires_human_action`) |
| `POST /api/v1/sessions/{id}/findings/{fid}/review` | **HITL Décision** : `confirmed_error`, `accepted_change`, `false_positive`, `needs_clarification`, commentaire, matérialité |
| `POST /api/v1/sessions/{id}/findings/batch-review` | Validation par lot (ex. accepter tous les écarts mineurs de forme) |
| `GET /api/v1/sessions/{id}/pdfs/{role}` | Servir les PDF originaux (`v0`, `v1`, `urd_n_minus_1`) pour affichage PDF.js |
| `GET /api/v1/sessions/{id}/export/annotated/{role}` | Télécharger le PDF `v0` ou `v1` annoté avec surlignage couleur |
| `GET /api/v1/sessions/{id}/export/report` | Télécharger le rapport exécutif Markdown |

### Format de localisation pour surlignage UI (`LocationRef`)
Chaque `Finding` contient `v0_location` et/ou `v1_location` :
- `page_number` (1-indexed)
- `page_width`, `page_height` (en points PDF)
- `bbox`: `{ x0, y0, x1, y1, nx0, ny0, nx1, ny1 }` — coordonnées PDF exactes **et** coordonnées normalisées `[0..1]` prêtes pour superposition sur un canvas PDF.js quel que soit le niveau de zoom.
- `section_title`, `table_id`, `cell_ref`, `quoted_text`.

---

## Déploiement sur GCP (Cloud Run + Vertex AI + Cloud Storage)

L'agent est conçu pour tourner de façon **stateless** sur **Google Cloud Run** (région Europe `europe-west1` par défaut), avec :
- **Vertex AI** (`URD_LLM_PROVIDER=vertexai`) via le compte de service IAM (sans clé API statique).
- **Google Cloud Storage (GCS)** (`URD_GCS_BUCKET`) pour persister les PDF, sessions, rendus et exports annotés entre instances Cloud Run.

### Déploiement en 1 commande (avec `gcloud` CLI)

```bash
cd /Users/paulbriand/.gemini/antigravity/scratch/urd-verifier-agent
chmod +x scripts/deploy_gcp.sh
PROJECT_ID=mon-projet-gcp REGION=europe-west1 ./scripts/deploy_gcp.sh
```

Ce script active les APIs (`run`, `cloudbuild`, `artifactregistry`, `storage`, `aiplatform`), crée le bucket GCS, crée un Service Account dédié (`roles/storage.objectAdmin` + `roles/aiplatform.user`), construit l'image Docker via [Dockerfile](file:///Users/paulbriand/.gemini/antigravity/scratch/urd-verifier-agent/Dockerfile) et déploie sur Cloud Run. Une pipeline [cloudbuild.yaml](file:///Users/paulbriand/.gemini/antigravity/scratch/urd-verifier-agent/cloudbuild.yaml) est également incluse.

---

## Tests

```bash
.venv/bin/pytest -v tests
```
