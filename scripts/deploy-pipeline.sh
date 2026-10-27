#!/usr/bin/env bash
# Deploy the pipeline (head) image: the container one Fargate task runs per genotyping job.
# Built on the OBITools image, so it carries Nextflow, OBITools, the bin/ scripts and the backend.
#
#   scripts/deploy-pipeline.sh [--allow-dirty]
#
# No service to restart: the next job picks up :latest. A job already running keeps its image.
set -euo pipefail

REGION=eu-central-1
ACCOUNT=236726878099
ECR="$ACCOUNT.dkr.ecr.$REGION.amazonaws.com"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [ "${1:-}" != "--allow-dirty" ] && [ -n "$(git status --porcelain -- backend deploy pipeline)" ]; then
  echo "Working tree has uncommitted changes under backend/ deploy/ pipeline/:" >&2
  git status --short -- backend deploy pipeline >&2
  echo "Commit them first, or re-run with --allow-dirty." >&2
  exit 1
fi

SHA=$(git rev-parse --short HEAD)
echo "[1/3] Building the pipeline image (amd64 — Fargate is x86) from $SHA …"
aws ecr get-login-password --region "$REGION" | docker login -u AWS --password-stdin "$ECR" >/dev/null
docker buildx build --platform linux/amd64 --provenance=false --sbom=false \
  -f deploy/Dockerfile.head \
  --build-arg OBITOOLS_IMAGE="$ECR/streamgt-obitools:latest" \
  -t "$ECR/streamgt-backend:latest" --push .

echo "[2/3] Tagging this build so it can be rolled back to…"
MANIFEST=$(aws ecr batch-get-image --region "$REGION" --repository-name streamgt-backend \
  --image-ids imageTag=latest --query 'images[0].imageManifest' --output text)
printf '%s' "$MANIFEST" > /tmp/streamgt-head-manifest.json
aws ecr put-image --region "$REGION" --repository-name streamgt-backend \
  --image-tag "head-$SHA" --image-manifest "file:///tmp/streamgt-head-manifest.json" \
  --query 'image.imageId.imageTag' --output text || echo "      (tag head-$SHA already exists)"
rm -f /tmp/streamgt-head-manifest.json

echo "[3/3] Done. The next submitted job runs this image ($SHA)."
echo "      Watch a run with: aws logs tail /ecs/streamgt-head --follow --region $REGION"
