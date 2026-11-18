#!/usr/bin/env bash
set -euo pipefail

# One-command deployment of URD Verifier Agent onto Google Cloud Run + Vertex AI + GCS.
# Usage:
#   PROJECT_ID=mon-projet-gcp REGION=europe-west1 ./scripts/deploy_gcp.sh

PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null || true)}"
REGION="${REGION:-europe-west1}"
SERVICE_NAME="${SERVICE_NAME:-urd-verifier-agent}"
BUCKET_NAME="${BUCKET_NAME:-${PROJECT_ID}-urd-verifier-sessions}"
SA_NAME="${SA_NAME:-urd-verifier-sa}"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

if [[ -z "${PROJECT_ID}" ]]; then
  echo "Erreur : définissez PROJECT_ID=<votre-id-projet-gcp>." >&2
  exit 1
fi

echo "==> Projet GCP : ${PROJECT_ID} | Région : ${REGION} | Service : ${SERVICE_NAME}"

# 1. Activer les APIs GCP nécessaires
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  storage.googleapis.com \
  aiplatform.googleapis.com \
  --project="${PROJECT_ID}"

# 2. Créer le bucket Cloud Storage pour les PDF, sessions et exports annotés
if ! gcloud storage buckets describe "gs://${BUCKET_NAME}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
  gcloud storage buckets create "gs://${BUCKET_NAME}" \
    --project="${PROJECT_ID}" \
    --location="${REGION}" \
    --uniform-bucket-level-access
fi

# 3. Créer le Service Account dédié (principe du moindre privilège : GCS + Vertex AI)
if ! gcloud iam service-accounts describe "${SA_EMAIL}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
  gcloud iam service-accounts create "${SA_NAME}" \
    --project="${PROJECT_ID}" \
    --display-name="URD Verifier Agent Cloud Run SA"
fi

gcloud storage buckets add-iam-policy-binding "gs://${BUCKET_NAME}" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/storage.objectAdmin"

gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/aiplatform.user" >/dev/null

# 4. Build & déploiement sur Cloud Run (source deploy via Cloud Build)
gcloud run deploy "${SERVICE_NAME}" \
  --source . \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --service-account="${SA_EMAIL}" \
  --memory=2Gi \
  --cpu=2 \
  --timeout=300 \
  --concurrency=10 \
  --allow-unauthenticated \
  --set-env-vars="URD_LLM_PROVIDER=vertexai,URD_VERTEX_PROJECT=${PROJECT_ID},URD_VERTEX_LOCATION=${REGION},URD_GCS_BUCKET=${BUCKET_NAME}"

URL=$(gcloud run services describe "${SERVICE_NAME}" --project="${PROJECT_ID}" --region="${REGION}" --format="value(status.url)")
echo ""
echo "==> Déploiement terminé !"
echo "    URL API : ${URL}"
echo "    Swagger : ${URL}/docs"
echo "    Health  : ${URL}/api/v1/health"
