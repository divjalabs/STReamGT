#!/usr/bin/env bash
# Deploy the API: build the Lambda image from the CURRENT commit, push it, roll the function.
#
#   scripts/deploy-api.sh [--allow-dirty]
#
# The image is built from the working tree, so an uncommitted change would ship without being
# recorded anywhere — hence the clean-tree check.
set -euo pipefail

REGION=eu-central-1
ACCOUNT=236726878099
ECR="$ACCOUNT.dkr.ecr.$REGION.amazonaws.com/streamgt-backend"
TAG=api-lambda
FUNCTION=streamgt-api
APP_URL=https://d2qy3qqpz2ebmu.cloudfront.net
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [ "${1:-}" != "--allow-dirty" ] && [ -n "$(git status --porcelain -- backend deploy pipeline)" ]; then
  echo "Working tree has uncommitted changes under backend/ deploy/ pipeline/:" >&2
  git status --short -- backend deploy pipeline >&2
  echo "Commit them first, or re-run with --allow-dirty." >&2
  exit 1
fi

SHA=$(git rev-parse --short HEAD)
echo "[1/4] Building the API image (arm64) from $SHA …"
aws ecr get-login-password --region "$REGION" | docker login -u AWS --password-stdin "${ECR%%/*}" >/dev/null
docker buildx build --platform linux/arm64 --provenance=false --sbom=false \
  -f deploy/Dockerfile.lambda -t "$ECR:$TAG" --push .

echo "[2/4] Pointing the Lambda at the new image…"
aws lambda update-function-code --region "$REGION" --function-name "$FUNCTION" \
  --image-uri "$ECR:$TAG" --query 'LastUpdateStatus' --output text

echo "[3/4] Waiting for the rollout…"
aws lambda wait function-updated --region "$REGION" --function-name "$FUNCTION"

echo "[4/4] Checking the live API…"
# /health sits outside the /api/* prefix, so CloudFront would route it to the SPA bucket —
# ask the function URL directly.
FURL=$(aws lambda get-function-url-config --region "$REGION" --function-name "$FUNCTION" \
  --query FunctionUrl --output text)
HEALTH=$(curl -s --max-time 30 "${FURL%/}/health" || true)
echo "      /health -> ${HEALTH:-<no response>}"
case "$HEALTH" in
  *'"status":"ok"'*) echo "Deployed $SHA. App: $APP_URL" ;;
  *) echo "API did not report healthy. Check: aws logs tail /aws/lambda/$FUNCTION --since 5m" >&2; exit 1 ;;
esac
