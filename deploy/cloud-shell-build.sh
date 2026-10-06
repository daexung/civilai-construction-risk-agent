#!/usr/bin/env bash
# Run inside the extracted deployment bundle in Google Cloud Shell.
# This builds an image; it does not publish a Cloud Run service.
set -euo pipefail
PROJECT_ID=civil-ai-jds
REGION=asia-northeast3
REPOSITORY=poomsemi
gcloud config set project "$PROJECT_ID"
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com
if ! gcloud artifacts repositories describe "$REPOSITORY" --location="$REGION" >/dev/null 2>&1; then
  gcloud artifacts repositories create "$REPOSITORY" --repository-format=docker --location="$REGION"
fi
IMAGE="$REGION-docker.pkg.dev/$PROJECT_ID/$REPOSITORY/api:$(date -u +%Y%m%d-%H%M%S)"
gcloud builds submit --tag "$IMAGE" .
printf '\nImage built: %s\nCloud Run has not been deployed by this script.\n' "$IMAGE"
