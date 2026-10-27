#!/usr/bin/env bash
# Deploy the SPA: build it, sync it to the site bucket, invalidate CloudFront, wait.
#
#   scripts/deploy-frontend.sh [--allow-dirty]
set -euo pipefail

REGION=eu-central-1
SITE_BUCKET=streamgt-site-236726878099
DISTRIBUTION=E2ZAMEAEERIVML
APP_URL=https://d2qy3qqpz2ebmu.cloudfront.net
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [ "${1:-}" != "--allow-dirty" ] && [ -n "$(git status --porcelain -- frontend)" ]; then
  echo "Working tree has uncommitted changes under frontend/:" >&2
  git status --short -- frontend >&2
  echo "Commit them first, or re-run with --allow-dirty." >&2
  exit 1
fi

SHA=$(git rev-parse --short HEAD)
echo "[1/4] Building the SPA from $SHA …"
( cd frontend && npm run build )

# Hashed assets are immutable and cached hard; index.html must never be cached, or a browser
# keeps asking for asset files that the next deploy has already deleted.
echo "[2/4] Uploading assets…"
aws s3 sync frontend/dist "s3://$SITE_BUCKET/" --delete --region "$REGION" \
  --exclude index.html --cache-control 'public,max-age=31536000,immutable' --only-show-errors
echo "[3/4] Uploading index.html…"
aws s3 cp frontend/dist/index.html "s3://$SITE_BUCKET/index.html" --region "$REGION" \
  --cache-control 'no-cache' --content-type 'text/html' --only-show-errors

echo "[4/4] Invalidating CloudFront…"
INV=$(aws cloudfront create-invalidation --distribution-id "$DISTRIBUTION" --paths '/*' \
  --query 'Invalidation.Id' --output text)
aws cloudfront wait invalidation-completed --distribution-id "$DISTRIBUTION" --id "$INV"

echo "Deployed $SHA to $APP_URL"
